"""``python -m scipy_india_kg.query`` — the MCP tools, on the command line.

Every subcommand mirrors one MCP tool by name (kebab-cased) and calls the same
:class:`~scipy_india_kg.graph.OrganizerGraph` method with the same arguments.
There is no Cypher here and none in the MCP server either; both are argument
parsing and formatting over the shared service, so the two cannot answer
differently.

That mirroring is NeoCarta's ``neocarta tool <name>`` idea, and it earns its
keep for the same reason: you can test and debug the exact retrieval an agent
will get without standing up an MCP client.

    python -m scipy_india_kg.query --help
    python -m scipy_india_kg.query list-unassigned-tasks
    python -m scipy_india_kg.query get-workgroup-context "Website & Tech"
    python -m scipy_india_kg.query search "code of conduct" --json

Read-only, like the server.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from .graph import open_graph
from .graph.service import SEARCH_KINDS, load_dotenv_if_present


def _json(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return json.dumps([item.model_dump(mode="json") for item in value], indent=2)
    return json.dumps(value.model_dump(mode="json"), indent=2)


# --------------------------------------------------------------------------- #
# Human-readable rendering. The --json output is the model dump, unchanged.
# --------------------------------------------------------------------------- #


def _task_line(task: Any, indent: str = "  ") -> str:
    owners = ", ".join(task.owners) if task.owners else "UNASSIGNED"
    where = task.workgroup_name or "no workgroup"
    due = f" due {task.due}" if task.due else ""
    seen = f" seen in {task.meeting_count}" if task.meeting_count > 1 else ""
    return f"{indent}[{task.status}] {task.description}\n{indent}    {where} · {owners}{due}{seen}"


def render(name: str, value: Any) -> str:
    if value is None:
        return "Not found."
    lines: list[str] = []

    if name == "describe-graph":
        lines.append(f"database: {value.database}")
        lines.append(f"search:   {value.search_strategy}")
        if value.build:
            lines.append(
                "build:    " + ", ".join(f"{k}={v}" for k, v in sorted(value.build.items()))
            )
        lines.append("nodes:    " + ", ".join(f"{k}={v}" for k, v in value.node_counts.items()))
        lines.append(
            "edges:    " + ", ".join(f"{k}={v}" for k, v in value.relationship_counts.items())
        )
        if value.full_text_indexes:
            lines.append("full-text indexes: " + ", ".join(value.full_text_indexes))
        if value.vector_indexes:
            lines.append("vector indexes:    " + ", ".join(value.vector_indexes))
        lines.extend(f"note: {note}" for note in value.notes)

    elif name == "list-recent-meetings":
        for meeting in value:
            lines.append(
                f"  {meeting.date} #{meeting.id} {meeting.title}\n"
                f"      facilitator {meeting.facilitator or 'not recorded'} · "
                f"{meeting.attendee_count} attendees · {meeting.decision_count} decisions · "
                f"{meeting.action_item_count} action items"
            )

    elif name == "get-meeting-context":
        meeting = value.meeting
        lines.append(f"{meeting.date} #{meeting.id} {meeting.title}")
        lines.append(f"  source: {meeting.source_ref}")
        lines.append(f"  attendees: {', '.join(value.attendees) or 'none recorded'}")
        if meeting.topics:
            lines.append("  topics: " + "; ".join(meeting.topics))
        if value.decisions:
            lines.append("  decisions:")
            lines.extend(
                f"    - {d.statement}" + (f"  [{d.workgroup_name}]" if d.workgroup_name else "")
                for d in value.decisions
            )
        if value.action_items:
            lines.append("  action items:")
            for item in value.action_items:
                moved = (
                    f" ({item.previous_status} -> {item.status_at_meeting})"
                    if item.previous_status and item.previous_status != item.status_at_meeting
                    else f" ({item.status_at_meeting})"
                )
                tag = " NEW" if item.is_new else ""
                owners = ", ".join(item.owners) or "unassigned"
                lines.append(f"    -{tag} {item.description}{moved} · {owners}")
        if value.joined_workgroups:
            lines.append("  joined: " + "; ".join(value.joined_workgroups))

    elif name in {"list-open-tasks", "list-unassigned-tasks"}:
        lines.extend(_task_line(task) for task in value)

    elif name == "get-task-history":
        for task in value:
            lines.append(f"{task.description}")
            lines.append(f"  id: {task.id}  (identity from {task.identity_basis})")
            lines.append(f"  now: {task.status}" + (f", due {task.due}" if task.due else ""))
            lines.append(f"  workgroup: {task.workgroup_name or 'none'}")
            lines.append(f"  owners: {', '.join(task.owners) or 'unassigned'}")
            lines.append(f"  source: {task.note_file} via {task.extraction_mode} extraction")
            if task.created_in:
                lines.append(
                    f"  created in: {task.created_in.date} {task.created_in.title} "
                    f"({task.created_in.source_ref})"
                )
            for point in task.history:
                lines.append(f"    {point.date} #{point.meeting_id} {point.title}: {point.status}")

    elif name == "get-person-context":
        lines.append(value.name + (" (volunteer)" if value.is_volunteer else ""))
        lines.append(f"  member of: {', '.join(value.member_of) or 'nothing yet'}")
        if value.awaiting_assignment_in:
            lines.append(f"  waiting on: {', '.join(value.awaiting_assignment_in)}")
        if value.availability:
            lines.append(f"  available: {value.availability}")
        if value.skills:
            lines.append(f"  skills: {', '.join(value.skills)}")
        lines.append(
            f"  {len(value.open_tasks)} open action items, "
            f"{value.completed_task_count} completed, "
            f"{len(value.meetings)} meetings, {value.facilitated_count} facilitated"
        )
        lines.extend(_task_line(task, "    ") for task in value.open_tasks)

    elif name == "get-workgroup-context":
        lines.append(f"{value.name} ({value.slug})")
        lines.append(f"  {value.description}")
        lines.append(f"  members: {', '.join(value.members) or 'nobody assigned yet'}")
        if value.awaiting_assignment:
            lines.append(
                "  awaiting assignment: "
                + ", ".join(f"{v.name} [{v.application_status}]" for v in value.awaiting_assignment)
            )
        lines.append(
            f"  open action items ({len(value.open_tasks)}), {value.done_task_count} done:"
        )
        lines.extend(_task_line(task, "    ") for task in value.open_tasks)
        if value.recent_decisions:
            lines.append("  decisions:")
            lines.extend(f"    - {d.date} {d.statement}" for d in value.recent_decisions)
        if value.recent_meetings:
            lines.append("  meetings:")
            lines.extend(f"    {m.date} #{m.id} {m.title}" for m in value.recent_meetings)

    elif name == "list-recent-decisions":
        for decision in value:
            where = f" [{decision.workgroup_name}]" if decision.workgroup_name else ""
            lines.append(f"  {decision.date}{where} {decision.statement}")
            lines.append(f"      from meetings {decision.meetings}")

    elif name == "find-interested-unassigned-volunteers":
        for volunteer in value:
            lines.append(
                f"  {volunteer.workgroup_name}: {volunteer.name} "
                f"[{volunteer.application_status}] available {volunteer.availability}"
            )
            if volunteer.skills:
                lines.append(f"      skills: {', '.join(volunteer.skills)}")

    elif name == "search":
        lines.append(f"query {value.query!r} · strategy {value.strategy}")
        if value.note:
            lines.append(f"  {value.note}")
        for hit in value.hits:
            extra = f" [{hit.status}]" if hit.status else ""
            lines.append(f"  {hit.score:.3f} {hit.kind:9} {hit.title}{extra}")
            if hit.snippet:
                lines.append(f"           {hit.snippet}")

    return "\n".join(lines) if lines else "(no results)"


# --------------------------------------------------------------------------- #
# Commands. Name, service call, and the arguments each takes.
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scipy_india_kg.query",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a summary")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("describe-graph", help="what this graph is and what search it supports")

    recent = subparsers.add_parser("list-recent-meetings", help="most recent meetings")
    recent.add_argument("--limit", type=int, default=5)

    meeting = subparsers.add_parser("get-meeting-context", help="one meeting in full")
    meeting.add_argument("--meeting-id", type=int, default=None)
    meeting.add_argument("--date", default=None, help="ISO date, YYYY-MM-DD")

    open_tasks = subparsers.add_parser("list-open-tasks", help="action items that are not done")
    open_tasks.add_argument("--workgroup", default=None)
    open_tasks.add_argument("--owner", default=None)
    open_tasks.add_argument("--limit", type=int, default=50)

    unassigned = subparsers.add_parser("list-unassigned-tasks", help="open items with no owner")
    unassigned.add_argument("--workgroup", default=None)
    unassigned.add_argument("--limit", type=int, default=50)

    history = subparsers.add_parser("get-task-history", help="provenance for an action item")
    history.add_argument("task", help="task id or part of its description")
    history.add_argument("--limit", type=int, default=3)

    person = subparsers.add_parser("get-person-context", help="one person's whole picture")
    person.add_argument("name")

    workgroup = subparsers.add_parser("get-workgroup-context", help="one workgroup's whole picture")
    workgroup.add_argument("workgroup")
    workgroup.add_argument("--recent-meetings", type=int, default=3)

    decisions = subparsers.add_parser("list-recent-decisions", help="decisions, newest first")
    decisions.add_argument("--workgroup", default=None)
    decisions.add_argument("--limit", type=int, default=10)

    waiting = subparsers.add_parser(
        "find-interested-unassigned-volunteers", help="volunteers still waiting on a workgroup"
    )
    waiting.add_argument("--workgroup", default=None)

    search = subparsers.add_parser("search", help="search_organizing_graph, on the CLI")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--kinds", nargs="*", choices=list(SEARCH_KINDS), default=None)

    return parser


async def run(args: argparse.Namespace) -> Any:
    async with open_graph() as graph:
        match args.command:
            case "describe-graph":
                return await graph.describe()
            case "list-recent-meetings":
                return await graph.list_recent_meetings(limit=args.limit)
            case "get-meeting-context":
                return await graph.get_meeting_context(meeting_id=args.meeting_id, date=args.date)
            case "list-open-tasks":
                return await graph.list_open_tasks(
                    workgroup=args.workgroup, owner=args.owner, limit=args.limit
                )
            case "list-unassigned-tasks":
                return await graph.list_unassigned_tasks(workgroup=args.workgroup, limit=args.limit)
            case "get-task-history":
                return await graph.get_task_history(args.task, limit=args.limit)
            case "get-person-context":
                return await graph.get_person_context(args.name)
            case "get-workgroup-context":
                return await graph.get_workgroup_context(
                    args.workgroup, recent_meetings=args.recent_meetings
                )
            case "list-recent-decisions":
                return await graph.list_recent_decisions(workgroup=args.workgroup, limit=args.limit)
            case "find-interested-unassigned-volunteers":
                return await graph.find_interested_unassigned_volunteers(workgroup=args.workgroup)
            case "search":
                return await graph.search(args.query, limit=args.limit, kinds=args.kinds)
        raise ValueError(f"unhandled command {args.command}")


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present()
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except Exception as error:  # noqa: BLE001 - a CLI should print, not traceback
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(_json(result) if args.json else render(args.command, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
