"""``OrganizerGraph``: one method per organizer question, read-only.

This is the layer the MCP server and the CLI both call. Neither of them holds
Cypher; both hold argument parsing and output formatting only. That is the point
of the split, and it is why an MCP tool and its CLI twin cannot answer
differently.

Read-only is enforced by the database, not by convention: every query runs with
``routing_=RoutingControl.READ``, and Neo4j refuses a write inside a read
transaction. ``tests/test_graph_readonly.py`` asserts that rather than assuming
it.
"""

from __future__ import annotations

import datetime
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, RoutingControl

from . import cypher
from .capabilities import (
    FULL_TEXT_INDEXES,
    NODE_COUNTS,
    REL_COUNTS,
    SEARCHABLE_LABELS,
    GraphCapabilities,
    SearchCapability,
    probe_capabilities,
)
from .models import (
    DecisionSummary,
    GraphReport,
    IssueSummary,
    MeetingContext,
    MeetingSummary,
    PersonContext,
    SearchHit,
    SearchResult,
    TaskChange,
    TaskDetail,
    TaskStatusPoint,
    TaskSummary,
    VolunteerInterest,
    WorkgroupContext,
)
from .search_text import embed_query, embedding_model_name, lucene_safe

KIND_BY_LABEL = {
    "Meeting": "meeting",
    "Task": "task",
    "Decision": "decision",
    "Workgroup": "workgroup",
}
LABEL_BY_KIND = {kind: label for label, kind in KIND_BY_LABEL.items()}
SEARCH_KINDS = tuple(KIND_BY_LABEL[label] for label in SEARCHABLE_LABELS)


def _date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, datetime.date):
        return value
    to_native = getattr(value, "to_native", None)
    return to_native() if to_native else None


def _meeting(row: dict[str, Any]) -> MeetingSummary:
    return MeetingSummary(
        id=row["id"],
        date=_date(row["date"]),
        title=row.get("title") or "",
        summary=row.get("summary") or "",
        topics=row.get("topics") or [],
        facilitator=row.get("facilitator"),
        attendee_count=row.get("attendee_count") or 0,
        workgroups=row.get("workgroups") or [],
        decision_count=row.get("decision_count") or 0,
        action_item_count=row.get("action_item_count") or 0,
        source_ref=row.get("source_ref") or "",
    )


def _task(row: dict[str, Any]) -> TaskSummary:
    return TaskSummary(
        id=row["id"],
        description=row["description"],
        status=row["status"],
        due=row.get("due") or "",
        workgroup=row.get("workgroup"),
        workgroup_name=row.get("workgroup_name"),
        owners=row.get("owners") or [],
        first_seen=_date(row.get("first_seen")),
        last_seen=_date(row.get("last_seen")),
        meeting_count=row.get("meeting_count") or 0,
        identity_basis=row.get("identity_basis") or "",
    )


def _issue(row: dict[str, Any]) -> IssueSummary:
    return IssueSummary(
        key=row["key"],
        repo=row["repo"],
        number=row["number"],
        title=row["title"],
        url=row.get("url") or "",
        state=row.get("state") or "open",
        state_reason=row.get("state_reason") or "",
        labels=row.get("labels") or [],
        milestone=row.get("milestone") or "",
        comment_count=row.get("comment_count") or 0,
        updated_at=_date(row.get("updated_at")),
        workgroup=row.get("workgroup"),
        workgroup_name=row.get("workgroup_name"),
        owners=row.get("owners") or [],
        tracks=row.get("tracks") or [],
    )


def _decision(row: dict[str, Any]) -> DecisionSummary:
    return DecisionSummary(
        statement=row["statement"],
        workgroup=row.get("workgroup"),
        workgroup_name=row.get("workgroup_name"),
        date=_date(row.get("date")),
        meetings=row.get("meetings") or [],
    )


class OrganizerGraph:
    """Read-only access to the SciPy India organizing graph."""

    def __init__(
        self,
        driver: AsyncDriver,
        database: str = "neo4j",
        capabilities: GraphCapabilities | None = None,
    ) -> None:
        self._driver = driver
        self._database = database
        self._capabilities = capabilities or GraphCapabilities()

    @property
    def capabilities(self) -> GraphCapabilities:
        return self._capabilities

    async def _rows(self, statement: str, /, **params: Any) -> list[dict[str, Any]]:
        return await self._driver.execute_query(
            statement,
            parameters_=params,
            database_=self._database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda result: result.data(),
        )

    # ----------------------------------------------------------------- meetings

    async def list_recent_meetings(self, limit: int = 5) -> list[MeetingSummary]:
        rows = await self._rows(cypher.LIST_RECENT_MEETINGS, limit=limit)
        return [_meeting(row) for row in rows]

    async def get_meeting_context(
        self, meeting_id: int | None = None, date: str | None = None
    ) -> MeetingContext | None:
        rows = await self._rows(cypher.GET_MEETING, meeting_id=meeting_id, date=date)
        if not rows:
            return None
        meeting = _meeting(rows[0])
        attendees, decisions, actions, joiners = (
            await self._rows(cypher.GET_MEETING_ATTENDEES, meeting_id=meeting.id),
            await self._rows(cypher.GET_MEETING_DECISIONS, meeting_id=meeting.id),
            await self._rows(cypher.GET_MEETING_ACTION_ITEMS, meeting_id=meeting.id),
            await self._rows(cypher.GET_MEETING_JOINERS, meeting_id=meeting.id),
        )
        return MeetingContext(
            meeting=meeting,
            attendees=[
                f"{row['name']} (facilitator)" if row["is_organizer"] else row["name"]
                for row in attendees
            ],
            decisions=[_decision(row) for row in decisions],
            action_items=[
                TaskChange(
                    id=row["id"],
                    description=row["description"],
                    workgroup_name=row.get("workgroup_name"),
                    status_at_meeting=row["status_at_meeting"],
                    previous_status=row.get("previous_status"),
                    is_new=bool(row.get("is_new")),
                    owners=row.get("owners") or [],
                )
                for row in actions
            ],
            joined_workgroups=[row["entry"] for row in joiners],
        )

    # -------------------------------------------------------------------- tasks

    async def list_open_tasks(
        self, workgroup: str | None = None, owner: str | None = None, limit: int = 50
    ) -> list[TaskSummary]:
        rows = await self._rows(
            cypher.LIST_OPEN_TASKS,
            open_statuses=cypher.OPEN_STATUSES,
            workgroup=await self._resolve_workgroup(workgroup),
            owner=owner,
            limit=limit,
        )
        return [_task(row) for row in rows]

    async def list_unassigned_tasks(
        self, workgroup: str | None = None, limit: int = 50
    ) -> list[TaskSummary]:
        rows = await self._rows(
            cypher.LIST_UNASSIGNED_TASKS,
            open_statuses=cypher.OPEN_STATUSES,
            workgroup=await self._resolve_workgroup(workgroup),
            limit=limit,
        )
        return [_task(row) for row in rows]

    # ------------------------------------------------------------------ issues

    async def list_issues(
        self,
        state: str | None = "open",
        workgroup: str | None = None,
        owner: str | None = None,
        unassigned_only: bool = False,
        limit: int = 50,
    ) -> list[IssueSummary]:
        """Issues from the tracker. Pass ``state=None`` for closed ones too."""
        rows = await self._rows(
            cypher.LIST_ISSUES,
            state=state,
            workgroup=await self._resolve_workgroup(workgroup),
            owner=owner,
            unassigned_only=unassigned_only,
            limit=limit,
        )
        return [_issue(row) for row in rows]

    async def find_issue(self, issue: str, limit: int = 3) -> list[IssueSummary]:
        """One issue by number, key or a piece of its title."""
        rows = await self._rows(cypher.FIND_ISSUE, needle=issue, limit=limit)
        return [_issue(row) for row in rows]

    async def get_task_history(self, task: str, limit: int = 3) -> list[TaskDetail]:
        """Full provenance for an action item: where it came from, every meeting
        that touched it, and the status it carried each time.

        ``task`` is a task id or any substring of a description, because nobody
        types ids by hand.
        """
        rows = await self._rows(cypher.FIND_TASK, needle=task, limit=limit)
        details: list[TaskDetail] = []
        for row in rows:
            summary = _task(row)
            history = await self._rows(cypher.GET_TASK_HISTORY, task_id=summary.id)
            origin = await self._rows(cypher.GET_TASK_ORIGIN, task_id=summary.id)
            details.append(
                TaskDetail(
                    **summary.model_dump(),
                    note_file=row.get("note_file") or "",
                    extraction_mode=row.get("extraction_mode") or "",
                    created_in=_meeting(origin[0]) if origin else None,
                    history=[
                        TaskStatusPoint(
                            meeting_id=point["meeting_id"],
                            date=_date(point["date"]),
                            title=point.get("title") or "",
                            status=point["status"],
                            due=point.get("due") or "",
                        )
                        for point in history
                    ],
                )
            )
        return details

    # ------------------------------------------------------------------ people

    async def get_person_context(self, name: str) -> PersonContext | None:
        rows = await self._rows(cypher.GET_PERSON, name=name)
        if not rows:
            return None
        row = rows[0]
        resolved = row["name"]
        tasks = await self._rows(
            cypher.GET_PERSON_TASKS, name=resolved, open_statuses=cypher.OPEN_STATUSES
        )
        done = await self._rows(cypher.COUNT_PERSON_DONE, name=resolved)
        meetings = await self._rows(cypher.GET_PERSON_MEETINGS, name=resolved, limit=10)
        return PersonContext(
            name=resolved,
            is_volunteer=bool(row["is_volunteer"]),
            availability=row.get("availability") or "",
            skills=row.get("skills") or [],
            interests=row.get("interests") or [],
            member_of=row.get("member_of") or [],
            interested_in=row.get("interested_in") or [],
            awaiting_assignment_in=row.get("awaiting_assignment_in") or [],
            open_tasks=[_task(task) for task in tasks],
            completed_task_count=done[0]["count"] if done else 0,
            meetings=[_meeting(meeting) for meeting in meetings],
            facilitated_count=row.get("facilitated_count") or 0,
        )

    async def find_interested_unassigned_volunteers(
        self, workgroup: str | None = None
    ) -> list[VolunteerInterest]:
        rows = await self._rows(
            cypher.FIND_INTERESTED_UNASSIGNED, workgroup=await self._resolve_workgroup(workgroup)
        )
        return [
            VolunteerInterest(
                name=row["name"],
                workgroup=row["workgroup"],
                workgroup_name=row["workgroup_name"],
                application_status=row.get("application_status") or "",
                availability=row.get("availability") or "",
                skills=row.get("skills") or [],
                interests=row.get("interests") or [],
            )
            for row in rows
        ]

    # -------------------------------------------------------------- workgroups

    async def get_workgroup_context(
        self, workgroup: str, recent_meetings: int = 3, recent_decisions: int = 10
    ) -> WorkgroupContext | None:
        rows = await self._rows(cypher.GET_WORKGROUP, workgroup=workgroup)
        if not rows:
            return None
        slug, name, description = rows[0]["slug"], rows[0]["name"], rows[0]["description"] or ""
        members = await self._rows(cypher.GET_WORKGROUP_MEMBERS, workgroup=slug)
        tasks = await self._rows(
            cypher.GET_WORKGROUP_TASKS, workgroup=slug, open_statuses=cypher.OPEN_STATUSES
        )
        done = await self._rows(cypher.COUNT_WORKGROUP_DONE, workgroup=slug)
        decisions = await self._rows(cypher.LIST_DECISIONS, workgroup=slug, limit=recent_decisions)
        meetings = await self._rows(
            cypher.GET_WORKGROUP_MEETINGS, workgroup=slug, limit=recent_meetings
        )
        waiting = await self.find_interested_unassigned_volunteers(slug)
        return WorkgroupContext(
            slug=slug,
            name=name,
            description=description,
            members=[f"{row['name']} (via {row['source']})" for row in members],
            awaiting_assignment=waiting,
            open_tasks=[_task(task) for task in tasks],
            done_task_count=done[0]["count"] if done else 0,
            recent_decisions=[_decision(row) for row in decisions],
            recent_meetings=[_meeting(row) for row in meetings],
        )

    async def list_recent_decisions(
        self, workgroup: str | None = None, limit: int = 10
    ) -> list[DecisionSummary]:
        rows = await self._rows(
            cypher.LIST_DECISIONS,
            workgroup=await self._resolve_workgroup(workgroup),
            limit=limit,
        )
        return [_decision(row) for row in rows]

    async def _resolve_workgroup(self, workgroup: str | None) -> str | None:
        """Accept a slug or a display name. Returns None when nothing matches,
        which the queries read as "no filter" rather than "no results" - so a
        typo shows everything rather than silently showing nothing."""
        if not workgroup:
            return None
        rows = await self._rows(cypher.GET_WORKGROUP, workgroup=workgroup)
        return rows[0]["slug"] if rows else None

    # ------------------------------------------------------------------ search

    async def search(
        self, query: str, limit: int = 10, kinds: list[str] | None = None, alpha: float = 0.5
    ) -> SearchResult:
        """Search meetings, action items, decisions and workgroups.

        Which retrieval runs depends on what the database has: hybrid when both
        vector and full-text indexes are present and embeddings are configured,
        vector or full-text when only one is, and nothing at all when neither
        index has been built. The strategy is reported back so the caller knows
        what it got.
        """
        strategy = self._capabilities.strategy
        wanted = [k for k in (kinds or SEARCH_KINDS) if k in SEARCH_KINDS]
        available = [KIND_BY_LABEL[label] for label in self._capabilities.searchable_labels]
        searched = [kind for kind in wanted if kind in available]

        if strategy is SearchCapability.UNAVAILABLE or not searched:
            return SearchResult(
                query=query,
                strategy=SearchCapability.UNAVAILABLE.value,
                note=(
                    "No search index is built on this graph. Run "
                    "`python scripts/build_search_indexes.py` to enable full-text search. "
                    "The other tools do not need it."
                ),
            )

        safe = lucene_safe(query)
        if strategy is SearchCapability.FULL_TEXT:
            rows = await self._rows(
                cypher.FULL_TEXT_SEARCH, query=safe, kinds=searched, top_k=limit * 2, limit=limit
            )
            note = "Full-text retrieval. No embeddings configured, so matching is lexical."
        else:
            embedding = await embed_query(query)
            if embedding is None:
                rows = await self._rows(
                    cypher.FULL_TEXT_SEARCH,
                    query=safe,
                    kinds=searched,
                    top_k=limit * 2,
                    limit=limit,
                )
                strategy = SearchCapability.FULL_TEXT
                note = "Embedding the query failed; fell back to full-text retrieval."
            elif strategy is SearchCapability.VECTOR:
                rows = await self._rows(
                    cypher.VECTOR_SEARCH,
                    embedding=embedding,
                    kinds=searched,
                    top_k=limit * 2,
                    limit=limit,
                )
                note = f"Vector retrieval using {embedding_model_name()}."
            else:
                rows = await self._rows(
                    cypher.HYBRID_SEARCH,
                    query=safe,
                    embedding=embedding,
                    kinds=searched,
                    top_k=limit * 2,
                    limit=limit,
                    alpha=alpha,
                )
                note = (
                    f"Hybrid retrieval: full text blended with {embedding_model_name()} "
                    f"vectors at alpha={alpha}."
                )

        return SearchResult(
            query=query,
            strategy=strategy.value,
            searched_kinds=searched,
            hits=[self._hit(row, strategy.value) for row in rows],
            note=note,
        )

    @staticmethod
    def _hit(row: dict[str, Any], retrieval: str) -> SearchHit:
        node, kind = row["node"], row["kind"]
        if kind == "meeting":
            return SearchHit(
                kind=kind,
                id=str(node["id"]),
                title=node.get("title") or "",
                snippet=node.get("summary") or "; ".join(node.get("topics") or []),
                score=row["score"],
                retrieval=retrieval,
                date=_date(node.get("date")),
            )
        if kind == "task":
            return SearchHit(
                kind=kind,
                id=node["id"],
                title=node["description"],
                snippet=f"due {node['due']}" if node.get("due") else "",
                score=row["score"],
                retrieval=retrieval,
                status=node.get("status"),
                date=_date(node.get("last_seen")),
            )
        if kind == "decision":
            return SearchHit(
                kind=kind,
                id=node["statement"],
                title=node["statement"],
                score=row["score"],
                retrieval=retrieval,
                date=_date(node.get("first_seen")),
            )
        return SearchHit(
            kind=kind,
            id=node["slug"],
            title=node["name"],
            snippet=node.get("description") or "",
            score=row["score"],
            retrieval=retrieval,
        )

    # ------------------------------------------------------------------ report

    async def describe(self) -> GraphReport:
        nodes = await self._rows(NODE_COUNTS)
        rels = await self._rows(REL_COUNTS)
        caps = self._capabilities
        return GraphReport(
            database=self._database,
            node_counts={row["label"]: row["count"] for row in nodes if row["label"]},
            relationship_counts={row["type"]: row["count"] for row in rels},
            build=caps.build,
            search_strategy=caps.strategy.value,
            full_text_indexes=sorted(
                FULL_TEXT_INDEXES[label]
                for label in caps.full_text_labels
                if label in FULL_TEXT_INDEXES
            ),
            vector_indexes=sorted(caps.vector_labels),
            embeddings_configured=caps.embeddings_configured,
            notes=list(caps.notes),
        )


def load_dotenv_if_present(path: str | os.PathLike[str] | None = None) -> None:
    """Load .env if there is one. Existing environment variables win.

    Small on purpose: the MCP server is launched by a client that may pass no
    environment at all, and a hard dependency on python-dotenv for six lines is
    not worth it.
    """
    env_path = Path(path or Path.cwd() / ".env")
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


@asynccontextmanager
async def open_graph(
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
):
    """Connect, probe capabilities, yield an ``OrganizerGraph``, close.

    Reads NEO4J_* from the environment, same variables as the rest of the
    project. Never writes.
    """
    uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = user or os.environ.get("NEO4J_USER", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "scipyindia")
    database = database or os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        capabilities = await probe_capabilities(
            driver, database, embeddings_configured=bool(embedding_model_name())
        )
        yield OrganizerGraph(driver, database, capabilities)
    finally:
        await driver.close()
