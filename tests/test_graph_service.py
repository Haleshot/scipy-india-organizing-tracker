"""The retrieval layer, against whatever graph is loaded.

Skipped when Neo4j is not running. These are the same code paths the MCP tools
and the CLI take, so what passes here is what an agent gets.

These assert on shape, not on wording. The graph is built from notes the team
edits every week, so a test that knows a task is called "Port the 2025 site
template" fails the moment somebody rewords it, which is noise rather than a
regression. Content-specific behaviour, including the awkward cases, is covered
offline against tests/fixtures/corpus.
"""

import pytest

from neo4j_support import requires_neo4j

pytestmark = [requires_neo4j, pytest.mark.asyncio]


async def _any_task_seen_more_than_once(graph):
    """A task that appears in several meetings, or None when none does."""
    for task in await graph.list_open_tasks():
        detail = (await graph.get_task_history(task.description, limit=1))[0]
        if detail.meeting_count > 1:
            return detail
    return None


async def test_describes_where_the_graph_came_from(graph):
    report = await graph.describe()
    assert report.node_counts["Meeting"] >= 1
    assert report.build["notes_source"] in {"local", "google_drive"}
    assert report.build["extraction_mode"] in {"markdown", "llm"}
    # DECIDED points at decisions now; the old meeting-to-task DECIDED is gone.
    assert "CREATED_ACTION" in report.relationship_counts
    assert "TOUCHED_ACTION" in report.relationship_counts


async def test_open_tasks_exclude_finished_work(graph):
    for task in await graph.list_open_tasks():
        assert task.status in {"open", "in_progress", "blocked", "unknown"}


async def test_unassigned_tasks_really_have_no_owner(graph):
    unassigned = await graph.list_unassigned_tasks()
    assert unassigned, "the fixture is meant to contain unowned work"
    assert all(task.owners == [] for task in unassigned)


async def test_workgroup_filter_accepts_a_slug_or_a_display_name(graph):
    tasks = await graph.list_open_tasks()
    filed = next((t for t in tasks if t.workgroup), None)
    if filed is None:
        pytest.skip("no open task is filed under a workgroup right now")
    workgroup = await graph.get_workgroup_context(filed.workgroup)
    by_slug = await graph.list_open_tasks(workgroup=workgroup.slug)
    by_name = await graph.list_open_tasks(workgroup=workgroup.name)
    assert by_slug and {t.id for t in by_slug} == {t.id for t in by_name}


async def test_recurring_task_history_is_ordered_and_complete(graph):
    """A task carried across meetings keeps every appearance, in date order."""
    detail = await _any_task_seen_more_than_once(graph)
    if detail is None:
        pytest.skip("no open task has been discussed in more than one meeting")
    assert len(detail.history) == detail.meeting_count
    assert [point.date for point in detail.history] == sorted(p.date for p in detail.history)
    assert detail.status == detail.history[-1].status, "the node carries the latest status"


async def test_task_provenance_points_back_at_the_source(graph):
    task = (await graph.list_open_tasks())[0]
    detail = (await graph.get_task_history(task.description, limit=1))[0]
    assert detail.created_in is not None
    assert detail.created_in.date == detail.first_seen
    assert "#section-" in detail.created_in.source_ref
    assert detail.note_file
    assert detail.extraction_mode in {"markdown", "llm"}
    assert detail.identity_basis in {"explicit_id", "workgroup_description", "description"}


async def test_meeting_context_reports_status_transitions(graph):
    meetings = await graph.list_recent_meetings(1)
    context = await graph.get_meeting_context(meeting_id=meetings[0].id)
    moved = [
        item
        for item in context.action_items
        if item.previous_status and item.previous_status != item.status_at_meeting
    ]
    assert moved, "the latest fixture meeting is meant to move at least one item"
    assert any(item.is_new for item in context.action_items)


async def test_person_context_reports_membership_and_open_work(graph):
    task = next((t for t in await graph.list_open_tasks() if t.owners), None)
    if task is None:
        pytest.skip("nothing open is assigned to anyone right now")
    context = await graph.get_person_context(task.owners[0])
    assert context is not None
    assert task.description in [t.description for t in context.open_tasks]
    # Membership and interest are different things, and neither is inferred
    # from the other.
    assert not set(context.member_of) & set(context.awaiting_assignment_in)


async def test_membership_records_which_source_created_it(graph):
    """Every membership says where it came from, so none of it is a guess."""
    from scipy_india_kg.workgroups import default_registry

    seen = []
    for workgroup in default_registry():
        context = await graph.get_workgroup_context(workgroup.slug)
        if context:
            seen.extend(context.members)
    if not seen:
        pytest.skip("nobody is in a workgroup yet")
    assert all(
        "via meeting_notes" in member or "via volunteer_application" in member for member in seen
    )


async def test_partial_names_resolve_to_one_person(graph):
    task = next((t for t in await graph.list_open_tasks() if t.owners), None)
    if task is None:
        pytest.skip("nothing open is assigned to anyone right now")
    full = task.owners[0]
    assert (await graph.get_person_context(full.split()[0])).name == full


async def test_workgroup_context_is_one_call_for_where_are_we(graph):
    task = next((t for t in await graph.list_open_tasks() if t.workgroup), None)
    if task is None:
        pytest.skip("no open task is filed under a workgroup right now")
    context = await graph.get_workgroup_context(task.workgroup)
    assert context.slug == task.workgroup
    assert context.members
    assert context.open_tasks
    assert context.recent_meetings


async def test_an_empty_workgroup_is_visible_rather_than_missing(graph):
    context = await graph.get_workgroup_context("content")
    assert context is not None
    assert context.members == []
    assert context.open_tasks == []


async def test_interested_unassigned_excludes_declined_applicants(graph):
    """Nobody who withdrew or was declined shows up as waiting to be placed."""
    report = await graph.describe()
    if not report.node_counts.get("VolunteerApplication"):
        pytest.skip("no volunteer applications are loaded (VOLUNTEER_SOURCE=none)")
    for volunteer in await graph.find_interested_unassigned_volunteers():
        assert volunteer.status not in {"declined", "withdrawn"}


async def test_unknown_names_return_nothing_rather_than_guessing(graph):
    assert await graph.get_person_context("Nobody McNobody") is None
    assert await graph.get_workgroup_context("quidditch") is None
    assert await graph.get_meeting_context(meeting_id=999999) is None
