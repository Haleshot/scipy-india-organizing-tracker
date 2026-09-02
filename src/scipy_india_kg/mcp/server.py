"""The SciPy India organizing MCP server.

Eleven tools, all read-only, all thin. Every one of them calls a method on
:class:`~scipy_india_kg.graph.OrganizerGraph`; there is no Cypher in this file
and no business logic. The CLI (``python -m scipy_india_kg.query``) wraps the
same methods, which is how the two stay honest with each other.

Three things are borrowed from NeoCarta and worth naming:

* **Capability-gated registration.** The database is probed at startup and the
  search tool is registered only when an index exists that can serve it. An
  agent is never handed a tool that cannot work.
* **Read-only at the application layer.** Queries run under
  ``RoutingControl.READ``, so Neo4j refuses a write in these transactions rather
  than trusting the caller, and there is no arbitrary-Cypher tool and no write
  tool of any kind. Worth being precise about the limit: this server connects
  with the same Neo4j account the pipeline writes with, so the *credential* is
  not read-only. For a stdio server on the organizer's own laptop that is the
  same trust boundary as the shell it was launched from. Anything that exposes
  this beyond one machine should give it a read-only Neo4j role first.
* **A build-metadata probe.** The pipeline writes a ``GraphBuild`` node, and
  ``describe_graph`` reports it, so the agent can tell fixture data from the
  real Drive folder before it answers a question about the conference.

What is deliberately *not* borrowed: NeoCarta's ontology (Database / Schema /
Table / Column), its connector framework, and its per-label registrar dispatch.
CocoIndex already owns ingestion here, and eleven fixed tools do not need a
dispatch table.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .. import __version__
from ..graph import OrganizerGraph, SearchCapability
from ..graph.service import SEARCH_KINDS

logger = logging.getLogger("scipy_india_kg.mcp")

SERVER_NAME = "scipy-india-organizing"

INSTRUCTIONS = """\
Read-only access to the SciPy India conference organizing graph: meetings and
what was decided in them, action items and who owns them, workgroups, and
volunteers.

Answer organizer questions from these tools rather than from files on disk. The
graph is the record; a fixture note file is not.

Start with `describe_graph` if you need to know what data this is (fixture or
real) and which retrieval the search tool can offer. Prefer the specific tools
over `search_organizing_graph` for anything countable: open work, unowned work,
one person's load, one workgroup's state. Use search for open-ended discovery.

Everything here reads. Nothing in this server can change the graph; to change
it, edit the meeting notes and re-run the pipeline.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)


def _dump(value: Any) -> Any:
    """Pydantic models to plain JSON-able data, dates as ISO strings."""
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if value is None:
        return None
    return value.model_dump(mode="json")


def build_server(graph: OrganizerGraph) -> MCPServer:
    """Register the tools this graph can actually serve."""
    server = MCPServer(
        name=SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        log_level="WARNING",
    )
    capabilities = graph.capabilities

    @server.tool(annotations=READ_ONLY)
    async def describe_graph() -> dict[str, Any]:
        """What this graph contains, where it came from, and what search it supports.

        Call this first when you need to know whether you are looking at fixture
        data or the real SciPy India notes, or why search is unavailable.
        Returns node and relationship counts, the pipeline's build record (source
        of the notes, extraction mode, person-resolution mode), and the retrieval
        strategy currently available.
        """
        return _dump(await graph.describe())

    @server.tool(annotations=READ_ONLY)
    async def list_recent_meetings(limit: int = 5) -> list[dict[str, Any]]:
        """The most recent organizing meetings, newest first.

        Each entry has the meeting id, date, title, facilitator, attendee count,
        workgroups discussed, and how many decisions and action items it
        touched. Pass an id to `get_meeting_context` for the detail.

        Parameters
        ----------
        limit: how many meetings to return.
        """
        return _dump(await graph.list_recent_meetings(limit=limit))

    @server.tool(annotations=READ_ONLY)
    async def get_meeting_context(
        meeting_id: int | None = None, date: str | None = None
    ) -> dict[str, Any] | None:
        """Everything one meeting recorded: attendees, decisions, action items, joiners.

        Each action item comes back with the status it carried at this meeting
        and the status it carried at the previous meeting that touched it, plus
        whether this meeting created it. That is what makes "what changed
        between the last two meetings" answerable: call this for both and
        compare, rather than replaying the whole history.

        Parameters
        ----------
        meeting_id: the id from `list_recent_meetings`.
        date: an ISO date (YYYY-MM-DD) instead of an id. The most recent meeting
            is returned when neither is given.
        """
        return _dump(await graph.get_meeting_context(meeting_id=meeting_id, date=date))

    @server.tool(annotations=READ_ONLY)
    async def list_open_tasks(
        workgroup: str | None = None, owner: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Action items that are not done, with their owners and workgroups.

        "Open" means open, in progress, blocked, or unknown. Unknown is included
        because the notes not saying an item is finished is not evidence that it
        is.

        Parameters
        ----------
        workgroup: filter by slug or display name ("website-tech", "Website & Tech").
        owner: filter to one person's exact canonical name.
        limit: maximum rows.
        """
        return _dump(await graph.list_open_tasks(workgroup=workgroup, owner=owner, limit=limit))

    @server.tool(annotations=READ_ONLY)
    async def list_unassigned_tasks(
        workgroup: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Open action items with nobody assigned to them.

        The pipeline never guesses an owner, so an empty owner list means the
        notes genuinely did not name one. This is the list to bring to a meeting.

        Parameters
        ----------
        workgroup: filter by slug or display name.
        limit: maximum rows.
        """
        return _dump(await graph.list_unassigned_tasks(workgroup=workgroup, limit=limit))

    @server.tool(annotations=READ_ONLY)
    async def list_issues(
        state: str | None = "open",
        workgroup: str | None = None,
        owner: str | None = None,
        unassigned_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """GitHub issues from the planning tracker.

        Separate from the action items on purpose. An action item is what a
        meeting agreed to do; an issue is what somebody filed. They overlap, and
        where a note said so explicitly the issue's `tracks` field names the
        action item it belongs to. Everywhere else the two are unjoined, and
        that gap is usually the interesting thing.

        Parameters
        ----------
        state: "open", "closed", or None for both.
        workgroup: filter by slug or display name, from the issue's labels.
        owner: filter to one person's exact canonical name.
        unassigned_only: only issues with nobody assigned on GitHub.
        limit: maximum rows.
        """
        return _dump(
            await graph.list_issues(
                state=state,
                workgroup=workgroup,
                owner=owner,
                unassigned_only=unassigned_only,
                limit=limit,
            )
        )

    @server.tool(annotations=READ_ONLY)
    async def find_issue(issue: str, limit: int = 3) -> list[dict[str, Any]]:
        """One issue by number, by owner/repo#number, or by part of its title.

        Parameters
        ----------
        issue: "44", "#44", "scipy-india/planning#44", or a piece of the title.
        limit: how many matches to return when the title is ambiguous.
        """
        return _dump(await graph.find_issue(issue, limit=limit))

    @server.tool(annotations=READ_ONLY)
    async def get_task_history(task: str, limit: int = 3) -> list[dict[str, Any]]:
        """Provenance for an action item: origin, every meeting that touched it, status each time.

        Use this to answer "why does the graph believe this?". Returns the
        meeting that created the item, the source reference into the notes
        document, which extraction mode produced it, how its identity was
        derived, and the full status history in date order.

        Parameters
        ----------
        task: a task id, or any part of its description.
        limit: how many matching tasks to return when the description is ambiguous.
        """
        return _dump(await graph.get_task_history(task, limit=limit))

    @server.tool(annotations=READ_ONLY)
    async def get_person_context(name: str) -> dict[str, Any] | None:
        """One person: their workgroups, open action items, meetings and volunteer profile.

        Also reports the workgroups they said they were interested in but have
        not been assigned to, which is usually the actionable part.

        Parameters
        ----------
        name: full or partial name; the closest canonical match is used.
        """
        return _dump(await graph.get_person_context(name))

    @server.tool(annotations=READ_ONLY)
    async def get_workgroup_context(
        workgroup: str, recent_meetings: int = 3
    ) -> dict[str, Any] | None:
        """One workgroup: members, people waiting on it, open work, recent decisions and meetings.

        The single call to make when someone asks "where are we on X".

        Parameters
        ----------
        workgroup: slug or display name.
        recent_meetings: how many of the meetings that discussed it to include.
        """
        return _dump(await graph.get_workgroup_context(workgroup, recent_meetings=recent_meetings))

    @server.tool(annotations=READ_ONLY)
    async def list_recent_decisions(
        workgroup: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Decisions the meetings recorded, newest first, with the meetings they came from.

        Decisions are separate from action items here: a decision is something
        the team settled, an action item is something somebody has to do.

        Parameters
        ----------
        workgroup: filter to decisions concerning one workgroup.
        limit: maximum rows.
        """
        return _dump(await graph.list_recent_decisions(workgroup=workgroup, limit=limit))

    @server.tool(annotations=READ_ONLY)
    async def find_interested_unassigned_volunteers(
        workgroup: str | None = None,
    ) -> list[dict[str, Any]]:
        """Volunteers who asked for a workgroup and have not been put on it.

        Declined and withdrawn applications are excluded. Returns availability
        and skills alongside the name, which is what you need to decide who to
        contact.

        Parameters
        ----------
        workgroup: narrow to one workgroup by slug or display name.
        """
        return _dump(await graph.find_interested_unassigned_volunteers(workgroup=workgroup))

    if capabilities.strategy is not SearchCapability.UNAVAILABLE:
        strategy = capabilities.strategy.value

        # The description is built rather than written as a docstring because it
        # names the retrieval strategy this particular database can serve, and
        # an f-string is not a docstring.
        description = (
            "Search meetings, action items, decisions and workgroups by text.\n\n"
            f"Currently serving {strategy} retrieval"
            + (
                ", which combines keyword matching with semantic similarity.\n\n"
                if strategy == "hybrid"
                else ", which is keyword matching only.\n\n"
                if strategy == "full_text"
                else ", which is semantic similarity only.\n\n"
            )
            + "Use this for open-ended discovery. For anything you want counted or "
            "filtered exactly (open work, unowned work, one person's load), the "
            "specific tools are better.\n\n"
            "Volunteer application text is deliberately not searchable.\n\n"
            "Parameters\n----------\n"
            "query: a natural-language phrase or keywords.\n"
            "limit: maximum hits.\n"
            f"kinds: restrict to some of {list(SEARCH_KINDS)}."
        )

        @server.tool(annotations=READ_ONLY, description=description)
        async def search_organizing_graph(
            query: str, limit: int = 10, kinds: list[str] | None = None
        ) -> dict[str, Any]:
            return _dump(await graph.search(query, limit=limit, kinds=kinds))

        logger.info("Registered search_organizing_graph with %s retrieval", strategy)
    else:
        logger.warning(
            "No search index found; search_organizing_graph not registered. "
            "Run scripts/build_search_indexes.py to enable it."
        )

    return server


async def serve() -> None:
    """Connect to Neo4j, probe it, and serve over stdio."""
    from ..graph import open_graph

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    _quiet_dependencies()
    async with open_graph() as graph:
        report = await graph.describe()
        # stdout belongs to the MCP protocol; every diagnostic goes to stderr.
        print(
            f"{SERVER_NAME} {__version__}: database {report.database}, "
            f"{sum(report.node_counts.values())} nodes, search={report.search_strategy}, "
            f"source={report.build.get('notes_source', 'unknown')}",
            file=sys.stderr,
        )
        for note in report.notes:
            print(f"  note: {note}", file=sys.stderr)
        await build_server(graph).run_stdio_async()


# Libraries that chatter on stderr. An MCP client shows the server's stderr to
# the user, so a model-loading progress bar reads as something being wrong.
NOISY_LOGGERS = (
    "httpx",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
    "urllib3",
    "neo4j",
)


def _quiet_dependencies() -> None:
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")


def main() -> None:
    import asyncio

    from ..graph.service import load_dotenv_if_present

    load_dotenv_if_present()
    _quiet_dependencies()
    asyncio.run(serve())
