"""Graph rows and extraction schemas.

Two families of types live here:

* ``@dataclass`` rows: what lands in Neo4j. One per node label, plus payload
  classes for the relationships that carry properties.
* ``pydantic.BaseModel`` schemas: what the extractor returns. Both the LLM
  extractor and the deterministic Markdown extractor produce ``ExtractedMeeting``,
  so the rest of the pipeline never knows which one ran.

Anything the notes don't state stays empty. There is no default owner, no
default status, no inferred decision.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

import pydantic

# Statuses we recognise on an action item. "unknown" is the honest answer when
# the notes don't say, and it is the default everywhere.
TASK_STATUSES = ("unknown", "open", "in_progress", "blocked", "done", "dropped")

# Statuses on a volunteer application.
APPLICATION_STATUSES = (
    "submitted",
    "under_review",
    "accepted",
    "assigned",
    "declined",
    "withdrawn",
)


# ---------------------------------------------------------------------------
# Neo4j node rows
# ---------------------------------------------------------------------------


@dataclass
class Meeting:
    id: int  # stable, generated from (note_file, date) by CocoIndex's IdGenerator
    note_file: str
    date: datetime.date
    title: str
    summary: str
    topics: list[str]
    # Provenance. Answers "where in which document did this come from, and what
    # read it" without keeping a copy of the source text in the graph.
    section_index: int  # 0-based position of the section within the note file
    source_ref: str  # "<note_file>#section-<n>", enough to find it by hand
    extraction_mode: str  # "markdown" | "llm"


@dataclass
class Person:
    name: str  # canonical, after entity resolution


@dataclass
class Task:
    """An action item.

    ``id`` is the primary key, not ``description``. See ``task_identity`` for
    how it is derived and why description alone is not enough. ``description``,
    ``status`` and ``due`` are the values as the most recent meeting recorded
    them; the per-meeting history lives on the TOUCHED_ACTION edges.
    """

    id: str
    description: str
    status: str  # one of TASK_STATUSES
    due: str  # free text as written in the notes ("before 14 Feb"), "" if absent
    # Provenance.
    note_file: str
    identity_basis: str  # one of task_identity.IDENTITY_BASES
    first_seen: datetime.date
    last_seen: datetime.date
    meeting_count: int
    extraction_mode: str


@dataclass
class Workgroup:
    slug: str
    name: str
    description: str


@dataclass
class Decision:
    statement: str
    note_file: str
    first_seen: datetime.date
    extraction_mode: str


@dataclass
class VolunteerApplication:
    """The graph-side view of an application.

    Contact details live here because Neo4j is the private store. The public
    snapshot exporter allowlists fields explicitly and never reaches them.
    """

    application_id: str
    display_name: str
    status: str
    availability: str
    interests: list[str]
    skills: list[str]
    submitted_on: datetime.date
    contact_email: str
    contact_phone: str
    raw_response: str


# ---------------------------------------------------------------------------
# Relationship payloads
# ---------------------------------------------------------------------------


@dataclass
class AttendedRel:
    """``Person -[:ATTENDED]-> Meeting``. PK is derived from the endpoints."""

    is_organizer: bool


@dataclass
class MemberOfRel:
    """``Person -[:MEMBER_OF]-> Workgroup``, with where the assignment came from."""

    source: str  # "meeting_notes" | "volunteer_application"
    first_meeting_id: int  # -1 when the membership came from an application
    first_seen: datetime.date


@dataclass
class TouchedActionRel:
    """``Meeting -[:TOUCHED_ACTION]-> Task``: one edge per appearance.

    This is the audit trail for a recurring action item. The status and deadline
    are as that meeting recorded them, so the graph holds the whole
    open -> blocked -> in_progress history rather than only the latest value.
    """

    date: datetime.date
    status: str
    due: str


@dataclass
class AssignedToRel:
    """``Person -[:ASSIGNED_TO]-> Task``, with the meeting that first said so."""

    first_meeting_id: int
    first_seen: datetime.date


@dataclass
class BelongsToRel:
    """``Task -[:BELONGS_TO]-> Workgroup``, with the meeting that first said so."""

    first_meeting_id: int
    first_seen: datetime.date


@dataclass
class GraphBuild:
    """A singleton node recording how this graph was built.

    Borrowed from NeoCarta, which writes a ``__neocarta_graph__`` node on every
    connector run so its MCP server can tell which version produced the graph it
    is reading. The same idea answers two questions here: the dashboard footer
    can say whether it is looking at fixtures or a real Drive folder, and the MCP
    server can report what it is connected to.

    Configuration *names* only. No credentials, no folder ids, no paths.
    """

    id: str  # always "singleton"
    built_at: datetime.datetime
    pipeline_version: str
    notes_source: str  # "local" | "google_drive"
    volunteer_source: str  # "local" | "google_sheet" | "none"
    extraction_mode: str  # "markdown" | "llm"
    person_resolution: str  # "exact" | "embedding"
    workgroup_config: str  # basename of the registry file


# CREATED_ACTION, DECIDED, DISCUSSED, CONCERNS, INTERESTED_IN and SUBMITTED
# carry no payload. The Neo4j connector derives their identity from
# (from_id, to_id), giving exactly one edge per pair.


# ---------------------------------------------------------------------------
# Extraction schemas
# ---------------------------------------------------------------------------


class ExtractedPerson(pydantic.BaseModel):
    name: str = pydantic.Field(description="Full name of the person, as written in the note.")


class ExtractedTask(pydantic.BaseModel):
    description: str = pydantic.Field(
        description="Concise, standalone description of the action item."
    )
    owners: list[ExtractedPerson] = pydantic.Field(
        default_factory=list,
        description=(
            "People the action item is explicitly assigned to. Leave empty when the "
            "notes do not name an owner. Never guess."
        ),
    )
    workgroup: str | None = pydantic.Field(
        default=None,
        description=(
            "Workgroup slug this action item belongs to, chosen from the provided list. "
            "Null when the notes do not place it in a workgroup."
        ),
    )
    status: str = pydantic.Field(
        default="unknown",
        description=(
            "One of: unknown, open, in_progress, blocked, done, dropped. Use 'unknown' "
            "unless the notes state or clearly mark the status."
        ),
    )
    due: str = pydantic.Field(
        default="",
        description="Deadline exactly as written in the notes. Empty string if none is given.",
    )
    explicit_id: str | None = pydantic.Field(
        default=None,
        description=(
            "A stable id the notes gave this action item, written as 'id: some-slug'. "
            "Null when the notes do not give one. Never invent an id."
        ),
    )


class ExtractedDecision(pydantic.BaseModel):
    statement: str = pydantic.Field(
        description="A decision the meeting actually recorded, in one sentence."
    )
    workgroup: str | None = pydantic.Field(
        default=None,
        description="Workgroup slug the decision concerns, or null.",
    )


class ExtractedWorkgroupMove(pydantic.BaseModel):
    """A person joining a workgroup, as recorded in the notes."""

    person: ExtractedPerson
    workgroup: str = pydantic.Field(description="Workgroup slug the person joined.")


class ExtractedMeeting(pydantic.BaseModel):
    date: datetime.date = pydantic.Field(description="Meeting date in ISO format (YYYY-MM-DD).")
    title: str = pydantic.Field(default="", description="Heading of the meeting section.")
    summary: str = pydantic.Field(default="", description="A short summary of the meeting.")
    organizer: ExtractedPerson | None = pydantic.Field(
        default=None,
        description=(
            "The person who ran the meeting, only when the notes name a facilitator or "
            "organizer. Null otherwise."
        ),
    )
    attendees: list[ExtractedPerson] = pydantic.Field(
        default_factory=list,
        description="People recorded as attending, excluding the organizer.",
    )
    topics: list[str] = pydantic.Field(
        default_factory=list, description="Discussion topics covered."
    )
    workgroups: list[str] = pydantic.Field(
        default_factory=list,
        description="Workgroup slugs discussed in this meeting, from the provided list.",
    )
    decisions: list[ExtractedDecision] = pydantic.Field(default_factory=list)
    tasks: list[ExtractedTask] = pydantic.Field(default_factory=list)
    workgroup_moves: list[ExtractedWorkgroupMove] = pydantic.Field(
        default_factory=list,
        description="People the notes record as joining a workgroup.",
    )


# ---------------------------------------------------------------------------
# Volunteer application record (source-adapter output, pre-graph)
# ---------------------------------------------------------------------------


@dataclass
class VolunteerApplicationRecord:
    """What a volunteer-application source yields.

    ``contact_email``, ``contact_phone`` and ``raw_response`` are private. They
    reach Neo4j and stop there.
    """

    application_id: str
    name: str
    preferred_workgroups: list[str]
    interests: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    availability: str = ""
    status: str = "submitted"
    submitted_on: datetime.date = datetime.date.min
    assigned_workgroups: list[str] = field(default_factory=list)
    contact_email: str = ""
    contact_phone: str = ""
    raw_response: str = ""
