"""Result shapes returned by the retrieval layer.

Pydantic models rather than raw dicts so the MCP tools get a real output schema
and the CLI gets stable JSON. Every field here is something an organizer would
recognise from the notes.
"""

from __future__ import annotations

import datetime

import pydantic


class MeetingSummary(pydantic.BaseModel):
    id: int
    date: datetime.date
    title: str
    summary: str = ""
    topics: list[str] = pydantic.Field(default_factory=list)
    facilitator: str | None = None
    attendee_count: int = 0
    workgroups: list[str] = pydantic.Field(default_factory=list)
    decision_count: int = 0
    action_item_count: int = 0
    source_ref: str = ""


class TaskStatusPoint(pydantic.BaseModel):
    """One appearance of an action item in one meeting."""

    meeting_id: int
    date: datetime.date
    title: str
    status: str
    due: str = ""


class TaskSummary(pydantic.BaseModel):
    id: str
    description: str
    status: str
    due: str = ""
    workgroup: str | None = None
    workgroup_name: str | None = None
    owners: list[str] = pydantic.Field(default_factory=list)
    first_seen: datetime.date | None = None
    last_seen: datetime.date | None = None
    meeting_count: int = 0
    identity_basis: str = ""


class IssueSummary(pydantic.BaseModel):
    """A GitHub issue as the retrieval layer returns it.

    ``tracks`` holds the action items a note explicitly linked to this issue,
    which is empty for most of them and is the only join between the two
    sources.
    """

    key: str
    repo: str
    number: int
    title: str
    url: str
    state: str
    state_reason: str = ""
    labels: list[str] = pydantic.Field(default_factory=list)
    milestone: str = ""
    comment_count: int = 0
    updated_at: datetime.date | None = None
    workgroup: str | None = None
    workgroup_name: str | None = None
    owners: list[str] = pydantic.Field(default_factory=list)
    tracks: list[str] = pydantic.Field(default_factory=list)


class TaskDetail(TaskSummary):
    """A task plus the provenance behind it."""

    created_in: MeetingSummary | None = None
    history: list[TaskStatusPoint] = pydantic.Field(default_factory=list)
    note_file: str = ""
    extraction_mode: str = ""


class TaskChange(pydantic.BaseModel):
    """How an action item's status moved at one meeting."""

    id: str
    description: str
    workgroup_name: str | None = None
    status_at_meeting: str
    previous_status: str | None = None
    is_new: bool = False
    owners: list[str] = pydantic.Field(default_factory=list)


class DecisionSummary(pydantic.BaseModel):
    statement: str
    workgroup: str | None = None
    workgroup_name: str | None = None
    date: datetime.date | None = None
    meetings: list[int] = pydantic.Field(default_factory=list)


class MeetingContext(pydantic.BaseModel):
    meeting: MeetingSummary
    attendees: list[str] = pydantic.Field(default_factory=list)
    decisions: list[DecisionSummary] = pydantic.Field(default_factory=list)
    action_items: list[TaskChange] = pydantic.Field(default_factory=list)
    joined_workgroups: list[str] = pydantic.Field(default_factory=list)


class PersonContext(pydantic.BaseModel):
    name: str
    is_volunteer: bool = False
    availability: str = ""
    skills: list[str] = pydantic.Field(default_factory=list)
    interests: list[str] = pydantic.Field(default_factory=list)
    member_of: list[str] = pydantic.Field(default_factory=list)
    interested_in: list[str] = pydantic.Field(default_factory=list)
    awaiting_assignment_in: list[str] = pydantic.Field(default_factory=list)
    open_tasks: list[TaskSummary] = pydantic.Field(default_factory=list)
    completed_task_count: int = 0
    meetings: list[MeetingSummary] = pydantic.Field(default_factory=list)
    facilitated_count: int = 0


class VolunteerInterest(pydantic.BaseModel):
    name: str
    workgroup: str
    workgroup_name: str
    application_status: str = ""
    availability: str = ""
    skills: list[str] = pydantic.Field(default_factory=list)
    interests: list[str] = pydantic.Field(default_factory=list)


class WorkgroupContext(pydantic.BaseModel):
    slug: str
    name: str
    description: str = ""
    members: list[str] = pydantic.Field(default_factory=list)
    awaiting_assignment: list[VolunteerInterest] = pydantic.Field(default_factory=list)
    open_tasks: list[TaskSummary] = pydantic.Field(default_factory=list)
    done_task_count: int = 0
    recent_decisions: list[DecisionSummary] = pydantic.Field(default_factory=list)
    recent_meetings: list[MeetingSummary] = pydantic.Field(default_factory=list)


class SearchHit(pydantic.BaseModel):
    kind: str  # "meeting" | "task" | "decision" | "workgroup"
    id: str
    title: str
    snippet: str = ""
    score: float = 0.0
    retrieval: str = ""  # "full_text" | "vector" | "hybrid"
    workgroup_name: str | None = None
    date: datetime.date | None = None
    status: str | None = None


class SearchResult(pydantic.BaseModel):
    query: str
    strategy: str  # "full_text" | "vector" | "hybrid" | "unavailable"
    searched_kinds: list[str] = pydantic.Field(default_factory=list)
    hits: list[SearchHit] = pydantic.Field(default_factory=list)
    note: str = ""


class GraphReport(pydantic.BaseModel):
    """What the retrieval layer is connected to and what it can do."""

    database: str
    node_counts: dict[str, int] = pydantic.Field(default_factory=dict)
    relationship_counts: dict[str, int] = pydantic.Field(default_factory=dict)
    build: dict[str, str] = pydantic.Field(default_factory=dict)
    search_strategy: str = "unavailable"
    full_text_indexes: list[str] = pydantic.Field(default_factory=list)
    vector_indexes: list[str] = pydantic.Field(default_factory=list)
    embeddings_configured: bool = False
    notes: list[str] = pydantic.Field(default_factory=list)
