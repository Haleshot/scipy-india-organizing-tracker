"""SciPy India meeting-notes and volunteer-coordination knowledge graph.

Adapted from CocoIndex's ``examples/meeting_notes_graph_neo4j``. The shape of
that example is intact (Drive source, per-note LLM extraction, person entity
resolution, Neo4j property graph, incremental re-processing) with three
additions for running a conference rather than minuting a team:

* workgroups, loaded from ``config/workgroups.yaml`` rather than hardcoded;
* volunteer applications from a separate source adapter;
* decisions as their own nodes, so "what did we decide about sponsorship" is a
  traversal instead of a text search.

The graph:

    Meeting    one per dated section of a notes document
    Person     canonical organizers, attendees, task owners and volunteers
    Task       action items, with status and deadline as last recorded
    Workgroup  from the registry
    Decision   a decision a meeting recorded
    VolunteerApplication  one per submitted application
    GraphBuild a singleton recording how this graph was built

    Person  -[:ATTENDED {is_organizer}]->        Meeting
    Meeting -[:DECIDED]->                        Decision
    Decision-[:CONCERNS]->                       Workgroup
    Meeting -[:CREATED_ACTION]->                 Task
    Meeting -[:TOUCHED_ACTION {date,status,due}]-> Task
    Person  -[:ASSIGNED_TO {first_meeting_id}]-> Task
    Task    -[:BELONGS_TO {first_meeting_id}]->  Workgroup
    Meeting -[:DISCUSSED]->                      Workgroup
    Person  -[:MEMBER_OF {source,first_seen}]->  Workgroup
    Person  -[:INTERESTED_IN]->                  Workgroup
    Person  -[:SUBMITTED]->                      VolunteerApplication

Two deliberate departures from upstream:

* Upstream has no Decision node, so it spends ``DECIDED`` on the meeting-to-task
  edge. Here a decision is a node, ``DECIDED`` points at it, and action items get
  ``CREATED_ACTION`` (the meeting that first recorded it) plus ``TOUCHED_ACTION``
  (every meeting that mentioned it, carrying the status at that point). "Seen in
  four meetings" and "created in January" are then two different traversals
  rather than one ambiguous one.
* Upstream keys a task by its description. Here it is keyed by a scoped id from
  ``task_identity``, so two workgroups can both have a "Send the reminder email"
  without silently becoming one task.

Phases, following upstream's reasoning that no single note's component may own
a node that several notes touch:

  1. Per note: split into meeting sections, extract, declare ``Meeting`` nodes,
     carry everything person- or task-shaped forward.
  2. Person entity resolution across every note and every application.
  3. One cross-cutting pass declares Workgroup, Task, Decision, Person and
     VolunteerApplication nodes plus every edge. Tasks live here rather than in
     phase 1 because the same action item recurs across meetings with a changing
     status, and the latest meeting's status is the one that should win.
"""

from __future__ import annotations

import asyncio
import datetime
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cocoindex as coco
from cocoindex.connectors import neo4j
from cocoindex.ops.entity_resolution import ResolvedEntities
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from cocoindex.resources.id import IdGenerator

from . import __version__, extraction, person_resolution
from .models import (
    AssignedToRel,
    AttendedRel,
    BelongsToRel,
    Decision,
    GraphBuild,
    Meeting,
    MemberOfRel,
    Person,
    Task,
    TouchedActionRel,
    VolunteerApplication,
    VolunteerApplicationRecord,
    Workgroup,
)
from .sources import meeting_note_source
from .task_identity import task_identity
from .volunteers import volunteer_source
from .workgroups import WorkgroupRegistry, default_registry

# ---------------------------------------------------------------------------
# Context keys
# ---------------------------------------------------------------------------

KG_DB = coco.ContextKey[neo4j.ConnectionFactory]("kg_db")
REGISTRY = coco.ContextKey[WorkgroupRegistry]("workgroup_registry", detect_change=True)
EXTRACTOR = coco.ContextKey[str]("meeting_extractor", detect_change=True)
LLM_MODEL = coco.ContextKey[str]("llm_model", detect_change=True)
PERSON_RESOLUTION = coco.ContextKey[str]("person_resolution", detect_change=True)
RESOLUTION_LLM_MODEL = coco.ContextKey[str]("resolution_llm_model", detect_change=True)
EMBEDDER = coco.ContextKey[Any]("embedder", detect_change=True)


@coco.lifespan
async def coco_lifespan(builder: coco.EnvironmentBuilder) -> AsyncIterator[None]:
    builder.provide(
        KG_DB,
        neo4j.ConnectionFactory(
            uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "scipyindia"),
            ),
            database=os.environ.get("NEO4J_DATABASE", "neo4j"),
        ),
    )
    builder.provide(REGISTRY, default_registry())
    builder.provide(EXTRACTOR, os.environ.get("MEETING_EXTRACTOR", "markdown").lower())
    builder.provide(LLM_MODEL, os.environ.get("LLM_MODEL", "openai/gpt-5-mini"))
    builder.provide(PERSON_RESOLUTION, os.environ.get("PERSON_RESOLUTION", "exact").lower())
    builder.provide(
        RESOLUTION_LLM_MODEL, os.environ.get("RESOLUTION_LLM_MODEL", "openai/gpt-5-mini")
    )
    # Loading the embedding model costs a few seconds and a download, so only do
    # it when the embedding resolver is actually selected.
    builder.provide(
        EMBEDDER,
        SentenceTransformerEmbedder("Snowflake/snowflake-arctic-embed-xs")
        if os.environ.get("PERSON_RESOLUTION", "exact").lower() == "embedding"
        else None,
    )
    yield


# ---------------------------------------------------------------------------
# Phase 1 → Phase 3 transfer types
# ---------------------------------------------------------------------------


@dataclass
class TaskMention:
    """One action item as one meeting recorded it.

    ``task_id`` is resolved during phase 1, while the note file is still in
    scope, so phase 3 can group mentions without re-deriving identity.
    """

    task_id: str
    identity_basis: str
    description: str
    status: str
    due: str
    workgroup: str | None
    owners: list[str]  # raw names, pre-resolution


@dataclass
class MeetingExtraction:
    meeting_id: int
    note_file: str
    date: datetime.date
    title: str
    organizer: str | None  # raw name
    attendees: list[str]  # raw names
    workgroups: list[str]
    decisions: list[tuple[str, str | None]]  # (statement, workgroup slug or None)
    tasks: list[TaskMention]
    moves: list[tuple[str, str]] = field(default_factory=list)  # (raw name, workgroup slug)


# ---------------------------------------------------------------------------
# Phase 1: per-note extraction
# ---------------------------------------------------------------------------


@coco.fn(memo=True)
async def extract_section(section_text: str) -> extraction.ExtractedMeeting | None:
    """Extract one meeting section. Memoised on the section's text, so editing
    one meeting in a long notes document re-extracts only that meeting."""
    registry = coco.use_context(REGISTRY)
    mode = coco.use_context(EXTRACTOR)
    if mode == "markdown":
        return extraction.extract_meeting_markdown(section_text, registry)
    if mode == "llm":
        return await extraction.extract_meeting_llm(
            section_text, registry, coco.use_context(LLM_MODEL)
        )
    raise ValueError(f"Unknown MEETING_EXTRACTOR={mode!r}. Use 'markdown' or 'llm'.")


@coco.fn(memo=True)
async def process_note_file(
    file: Any,
    meeting_table: neo4j.TableTarget[Meeting],
) -> list[MeetingExtraction]:
    text = await file.read_text()
    note_file = file.file_path.path.as_posix()
    extraction_mode = coco.use_context(EXTRACTOR)
    id_generator = IdGenerator()

    extractions: list[MeetingExtraction] = []
    for section_index, section in enumerate(extraction.split_meetings(text)):
        extracted = await extract_section(section)
        if extracted is None:
            # No date in the section: it is a preamble or a links list, not a
            # meeting. Skipping beats inventing a date.
            continue

        meeting_id = await id_generator.next_id(extracted.date)
        meeting_table.declare_record(
            row=Meeting(
                id=meeting_id,
                note_file=note_file,
                date=extracted.date,
                title=extracted.title,
                summary=extracted.summary,
                topics=list(extracted.topics),
                section_index=section_index,
                source_ref=f"{note_file}#section-{section_index}",
                extraction_mode=extraction_mode,
            )
        )

        mentions = []
        for task in extracted.tasks:
            identity = task_identity(
                note_file=note_file,
                description=task.description,
                workgroup=task.workgroup,
                explicit_id=task.explicit_id,
            )
            mentions.append(
                TaskMention(
                    task_id=identity.id,
                    identity_basis=identity.basis,
                    description=task.description,
                    status=task.status,
                    due=task.due,
                    workgroup=task.workgroup,
                    owners=[o.name for o in task.owners],
                )
            )

        extractions.append(
            MeetingExtraction(
                meeting_id=meeting_id,
                note_file=note_file,
                date=extracted.date,
                title=extracted.title,
                organizer=extracted.organizer.name if extracted.organizer else None,
                attendees=[p.name for p in extracted.attendees],
                workgroups=list(extracted.workgroups),
                decisions=[(d.statement, d.workgroup) for d in extracted.decisions],
                tasks=mentions,
                moves=[(m.person.name, m.workgroup) for m in extracted.workgroup_moves],
            )
        )
    return extractions


def _reject_duplicate_exports(meetings: list[MeetingExtraction]) -> None:
    """Stop two exports of the same document from becoming two sets of meetings.

    Downloading the notes again usually produces a new filename: "SciPy India
    2026 Meeting Notes (1).md" next to the one already there. Both get read,
    every meeting appears twice, and nothing looks wrong until somebody counts
    the open tasks. Since a date and title identify a meeting for a human, two
    files claiming the same one is a mistake worth refusing rather than
    reconciling.
    """
    seen: dict[tuple[datetime.date, str], str] = {}
    clashes: list[str] = []
    files: set[str] = set()
    for meeting in meetings:
        key = (meeting.date, meeting.title.strip().lower())
        first = seen.get(key)
        if first is None:
            seen[key] = meeting.note_file
        elif first != meeting.note_file:
            clashes.append(f"  {meeting.date} {meeting.title!r}: {first} and {meeting.note_file}")
            files.update((first, meeting.note_file))

    if not clashes:
        return
    raise ValueError(
        "The same meeting appears in more than one note file, which usually means "
        "two exports of the same document are sitting in the notes directory:\n"
        + "\n".join(clashes[:10])
        + (f"\n  ... and {len(clashes) - 10} more" if len(clashes) > 10 else "")
        + "\n\nDelete the older export, or set MEETING_NOTES_FILE to the one you want "
        "read. Files involved: " + ", ".join(sorted(files))
    )


# ---------------------------------------------------------------------------
# Phase 2: person entity resolution
# ---------------------------------------------------------------------------


@coco.fn(memo=True)
async def resolve_persons(raw_persons: set[str]) -> ResolvedEntities:
    mode = coco.use_context(PERSON_RESOLUTION)
    if mode == "exact":
        return person_resolution.resolve_exact(raw_persons)
    if mode == "embedding":
        return await person_resolution.resolve_embedding(
            raw_persons,
            coco.use_context(EMBEDDER),
            coco.use_context(RESOLUTION_LLM_MODEL),
        )
    raise ValueError(f"Unknown PERSON_RESOLUTION={mode!r}. Use 'exact' or 'embedding'.")


# ---------------------------------------------------------------------------
# Phase 3: nodes and edges that several notes touch
# ---------------------------------------------------------------------------


@coco.fn
async def declare_graph(
    meetings: list[MeetingExtraction],
    applications: list[VolunteerApplicationRecord],
    persons: ResolvedEntities,
    registry: WorkgroupRegistry,
    targets: dict[str, Any],
) -> None:
    extraction_mode = coco.use_context(EXTRACTOR)
    workgroup_table = targets["workgroup"]
    person_table = targets["person"]
    task_table = targets["task"]
    decision_table = targets["decision"]
    application_table = targets["application"]

    # --- How this graph was built. One node, overwritten every run. Mode names
    # only: no credentials, no folder ids, no paths.
    targets["build"].declare_record(
        row=GraphBuild(
            id="singleton",
            built_at=datetime.datetime.now(datetime.UTC),
            pipeline_version=__version__,
            notes_source=os.environ.get("MEETING_NOTES_SOURCE", "local").lower(),
            volunteer_source=os.environ.get("VOLUNTEER_SOURCE", "local").lower(),
            extraction_mode=extraction_mode,
            person_resolution=coco.use_context(PERSON_RESOLUTION),
            workgroup_config=Path(
                os.environ.get("WORKGROUPS_CONFIG", "config/workgroups.yaml")
            ).name,
        )
    )

    # --- Workgroups: the registry is the source of truth, so every configured
    # workgroup gets a node whether or not anyone has touched it yet. An empty
    # workgroup is a signal worth seeing.
    for workgroup in registry:
        workgroup_table.declare_record(
            row=Workgroup(
                slug=workgroup.slug, name=workgroup.name, description=workgroup.description
            )
        )

    # --- People
    for canonical in persons.canonicals():
        person_table.declare_record(row=Person(name=canonical))

    def canonical(name: str) -> str:
        return persons.canonical_of(name)

    # --- Tasks.
    #
    # Identity is the scoped key resolved in phase 1, not the description; see
    # task_identity for why. Mentions of one task are gathered in date order so
    # the node carries the latest wording, status and deadline while the
    # TOUCHED_ACTION edges keep the whole history.
    mentions_by_task: dict[str, list[tuple[datetime.date, int, TaskMention]]] = {}
    for meeting in meetings:
        for task in meeting.tasks:
            mentions_by_task.setdefault(task.task_id, []).append(
                (meeting.date, meeting.meeting_id, task)
            )

    task_note_file = {m.meeting_id: m.note_file for m in meetings}
    for task_id, mentions in mentions_by_task.items():
        mentions.sort(key=lambda item: (item[0], item[1]))
        first_date, first_meeting_id, _first = mentions[0]
        last_date, _last_meeting_id, latest_mention = mentions[-1]

        task_table.declare_record(
            row=Task(
                id=task_id,
                description=latest_mention.description,
                status=latest_mention.status,
                due=latest_mention.due,
                note_file=task_note_file[first_meeting_id],
                identity_basis=latest_mention.identity_basis,
                first_seen=first_date,
                last_seen=last_date,
                meeting_count=len({meeting_id for _d, meeting_id, _m in mentions}),
                extraction_mode=extraction_mode,
            )
        )

        # Origin, then every appearance including the origin, so "seen in N
        # meetings" is one traversal and "which meeting created it" is another.
        targets["created_action"].declare_relation(from_id=first_meeting_id, to_id=task_id)
        for date, meeting_id, mention in mentions:
            targets["touched_action"].declare_relation(
                from_id=meeting_id,
                to_id=task_id,
                record=TouchedActionRel(date=date, status=mention.status, due=mention.due),
            )

        # The workgroup a task belongs to, credited to the meeting that first
        # placed it there.
        for date, meeting_id, mention in mentions:
            if mention.workgroup:
                targets["belongs_to"].declare_relation(
                    from_id=task_id,
                    to_id=mention.workgroup,
                    record=BelongsToRel(first_meeting_id=meeting_id, first_seen=date),
                )
                break

    # --- Per-meeting edges.
    #
    # Every edge is collected into a set before it is declared. Action items and
    # decisions recur across meetings by design; that recurrence is how a task
    # changes status. A target state may only be declared once per key, so
    # the same (owner, task) pair mentioned in four meetings has to collapse to
    # one ASSIGNED_TO edge here.
    attended: dict[tuple[str, int], bool] = {}
    discussed: set[tuple[int, str]] = set()
    decisions: dict[str, tuple[str | None, datetime.date, str]] = {}
    decided: set[tuple[int, str]] = set()
    # (person, task_id) -> the earliest meeting that recorded the assignment.
    assigned: dict[tuple[str, str], tuple[int, datetime.date]] = {}

    for meeting in meetings:
        if meeting.organizer:
            attended[(canonical(meeting.organizer), meeting.meeting_id)] = True
        for attendee in meeting.attendees:
            attended.setdefault((canonical(attendee), meeting.meeting_id), False)

        for slug in meeting.workgroups:
            discussed.add((meeting.meeting_id, slug))

        for statement, slug in meeting.decisions:
            existing = decisions.get(statement)
            if existing is None:
                decisions[statement] = (slug, meeting.date, meeting.note_file)
            elif slug and existing[0] is None:
                decisions[statement] = (slug, existing[1], existing[2])
            decided.add((meeting.meeting_id, statement))

        for task in meeting.tasks:
            for owner in task.owners:
                key = (canonical(owner), task.task_id)
                seen = assigned.get(key)
                if seen is None or meeting.date < seen[1]:
                    assigned[key] = (meeting.meeting_id, meeting.date)

    for (name, meeting_id), is_organizer in attended.items():
        targets["attended"].declare_relation(
            from_id=name, to_id=meeting_id, record=AttendedRel(is_organizer=is_organizer)
        )
    for meeting_id, slug in discussed:
        targets["discussed"].declare_relation(from_id=meeting_id, to_id=slug)
    for statement, (slug, first_seen, note_file) in decisions.items():
        decision_table.declare_record(
            row=Decision(
                statement=statement,
                note_file=note_file,
                first_seen=first_seen,
                extraction_mode=extraction_mode,
            )
        )
        if slug:
            targets["concerns"].declare_relation(from_id=statement, to_id=slug)
    for meeting_id, statement in decided:
        targets["decided"].declare_relation(from_id=meeting_id, to_id=statement)
    for (owner, task_id), (meeting_id, first_seen) in assigned.items():
        targets["assigned_to"].declare_relation(
            from_id=owner,
            to_id=task_id,
            record=AssignedToRel(first_meeting_id=meeting_id, first_seen=first_seen),
        )

    # --- Workgroup membership. Meeting notes and accepted applications both
    # create it; the edge records which, so an organizer can tell a recorded
    # decision from a form field.
    memberships: dict[tuple[str, str], tuple[str, int, datetime.date]] = {}
    for meeting in meetings:
        for raw_name, slug in meeting.moves:
            key = (canonical(raw_name), slug)
            seen = memberships.get(key)
            if seen is None or meeting.date < seen[2]:
                memberships[key] = ("meeting_notes", meeting.meeting_id, meeting.date)
    for application in applications:
        for slug in application.assigned_workgroups:
            memberships.setdefault(
                (canonical(application.name), slug),
                ("volunteer_application", -1, application.submitted_on),
            )
    for (name, slug), (source, meeting_id, first_seen) in memberships.items():
        targets["member_of"].declare_relation(
            from_id=name,
            to_id=slug,
            record=MemberOfRel(source=source, first_meeting_id=meeting_id, first_seen=first_seen),
        )

    # --- Volunteer applications
    interested: set[tuple[str, str]] = set()
    for application in applications:
        application_table.declare_record(
            row=VolunteerApplication(
                application_id=application.application_id,
                display_name=application.name,
                status=application.status,
                availability=application.availability,
                interests=list(application.interests),
                skills=list(application.skills),
                submitted_on=application.submitted_on,
                contact_email=application.contact_email,
                contact_phone=application.contact_phone,
                raw_response=application.raw_response,
            )
        )
        targets["submitted"].declare_relation(
            from_id=canonical(application.name), to_id=application.application_id
        )
        for slug in application.preferred_workgroups:
            interested.add((canonical(application.name), slug))

    for name, slug in interested:
        targets["interested_in"].declare_relation(from_id=name, to_id=slug)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@coco.fn
async def app_main() -> None:
    registry = coco.use_context(REGISTRY)

    # --- Node targets
    meeting_table = await neo4j.mount_table_target(
        KG_DB,
        "Meeting",
        await neo4j.TableSchema.from_class(Meeting, primary_key="id"),
        primary_key="id",
    )
    person_table = await neo4j.mount_table_target(
        KG_DB,
        "Person",
        await neo4j.TableSchema.from_class(Person, primary_key="name"),
        primary_key="name",
    )
    task_table = await neo4j.mount_table_target(
        KG_DB,
        "Task",
        await neo4j.TableSchema.from_class(Task, primary_key="id"),
        primary_key="id",
    )
    workgroup_table = await neo4j.mount_table_target(
        KG_DB,
        "Workgroup",
        await neo4j.TableSchema.from_class(Workgroup, primary_key="slug"),
        primary_key="slug",
    )
    decision_table = await neo4j.mount_table_target(
        KG_DB,
        "Decision",
        await neo4j.TableSchema.from_class(Decision, primary_key="statement"),
        primary_key="statement",
    )
    application_table = await neo4j.mount_table_target(
        KG_DB,
        "VolunteerApplication",
        await neo4j.TableSchema.from_class(VolunteerApplication, primary_key="application_id"),
        primary_key="application_id",
    )
    build_table = await neo4j.mount_table_target(
        KG_DB,
        "GraphBuild",
        await neo4j.TableSchema.from_class(GraphBuild, primary_key="id"),
        primary_key="id",
    )

    # --- Relationship targets. Ones without a schema get their identity from
    # (from_id, to_id), so there is exactly one edge per pair.
    targets: dict[str, Any] = {
        "build": build_table,
        "workgroup": workgroup_table,
        "person": person_table,
        "task": task_table,
        "decision": decision_table,
        "application": application_table,
        "attended": await neo4j.mount_relation_target(
            KG_DB, "ATTENDED", person_table, meeting_table
        ),
        # Meeting -> Decision. Upstream's example spends DECIDED on the
        # meeting-to-task edge because it has no Decision node; here a decision
        # is a first-class node, so DECIDED points at the thing that was
        # decided and action items get their own origin/history edges below.
        "decided": await neo4j.mount_relation_target(
            KG_DB, "DECIDED", meeting_table, decision_table
        ),
        "created_action": await neo4j.mount_relation_target(
            KG_DB, "CREATED_ACTION", meeting_table, task_table
        ),
        "touched_action": await neo4j.mount_relation_target(
            KG_DB, "TOUCHED_ACTION", meeting_table, task_table
        ),
        "assigned_to": await neo4j.mount_relation_target(
            KG_DB, "ASSIGNED_TO", person_table, task_table
        ),
        "belongs_to": await neo4j.mount_relation_target(
            KG_DB, "BELONGS_TO", task_table, workgroup_table
        ),
        "discussed": await neo4j.mount_relation_target(
            KG_DB, "DISCUSSED", meeting_table, workgroup_table
        ),
        "concerns": await neo4j.mount_relation_target(
            KG_DB, "CONCERNS", decision_table, workgroup_table
        ),
        "member_of": await neo4j.mount_relation_target(
            KG_DB, "MEMBER_OF", person_table, workgroup_table
        ),
        "interested_in": await neo4j.mount_relation_target(
            KG_DB, "INTERESTED_IN", person_table, workgroup_table
        ),
        "submitted": await neo4j.mount_relation_target(
            KG_DB, "SUBMITTED", person_table, application_table
        ),
    }

    await coco.mount(
        coco.component_subpath("pipeline"),
        coco.auto_refresh(run_pipeline, interval=_live_interval()),
        registry,
        targets,
        meeting_table,
    )


def _live_interval() -> datetime.timedelta:
    """How often live mode re-reads the notes. Ignored in catch-up mode."""
    seconds = int(os.environ.get("LIVE_REFRESH_SECONDS", "20"))
    return datetime.timedelta(seconds=max(2, seconds))


async def run_pipeline(
    registry: WorkgroupRegistry,
    targets: dict[str, Any],
    meeting_table: neo4j.TableTarget[Meeting],
) -> None:
    """One pass over the sources: extract, resolve, declare.

    Wrapped in ``coco.auto_refresh`` above, which runs it once and exits in
    catch-up mode and loops on an interval under ``update -L``. Polling rather
    than filesystem events, because phases 2 and 3 need every note at once:
    person resolution has to see all the names before it can decide which are
    the same person, so there is nothing useful to do with a single changed
    file on its own. Memoisation is what makes the polling cheap. A cycle with
    no edits re-reads the files, matches every section against its cached
    extraction, and declares the same target state, so nothing is written.
    """
    # --- Phase 1
    source = meeting_note_source()
    file_coros = [
        coco.use_mount(
            coco.component_subpath("note", path_key), process_note_file, file, meeting_table
        )
        async for path_key, file in source.items()
    ]
    per_file: list[list[MeetingExtraction]] = list(await asyncio.gather(*file_coros))
    all_meetings = [m for group in per_file for m in group]
    all_meetings.sort(key=lambda m: (m.date, m.meeting_id))
    _reject_duplicate_exports(all_meetings)

    # --- Volunteer applications
    applications = await volunteer_source(registry).applications()

    # --- Phase 2
    raw_persons: set[str] = set()
    for meeting in all_meetings:
        if meeting.organizer:
            raw_persons.add(meeting.organizer)
        raw_persons.update(meeting.attendees)
        raw_persons.update(name for name, _ in meeting.moves)
        for task in meeting.tasks:
            raw_persons.update(task.owners)
    raw_persons.update(a.name for a in applications)

    persons = await coco.use_mount(
        coco.component_subpath("resolve_persons"), resolve_persons, raw_persons
    )

    # --- Phase 3
    await coco.mount(
        coco.component_subpath("graph"),
        declare_graph,
        all_meetings,
        applications,
        persons,
        registry,
        targets,
    )


app = coco.App(coco.AppConfig(name="SciPyIndiaMeetingNotesGraph"), app_main)
