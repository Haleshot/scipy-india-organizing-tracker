"""The retrieval layer, against the live fixture graph.

Skipped when Neo4j is not running. These are the same code paths the MCP tools
and the CLI take, so what passes here is what an agent gets.
"""

import pytest

from neo4j_support import requires_neo4j

pytestmark = [requires_neo4j, pytest.mark.asyncio]


async def test_describes_where_the_graph_came_from(graph):
    report = await graph.describe()
    assert report.node_counts["Meeting"] >= 5
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
    by_slug = await graph.list_open_tasks(workgroup="website-tech")
    by_name = await graph.list_open_tasks(workgroup="Website & Tech")
    assert by_slug and {t.id for t in by_slug} == {t.id for t in by_name}


async def test_recurring_task_history_is_ordered_and_complete(graph):
    detail = (await graph.get_task_history("Port the 2025 site template"))[0]
    assert detail.meeting_count == 3
    assert [point.status for point in detail.history] == ["open", "blocked", "in_progress"]
    assert [point.date for point in detail.history] == sorted(p.date for p in detail.history)
    assert detail.status == "in_progress", "the node carries the latest status"


async def test_task_provenance_points_back_at_the_source(graph):
    detail = (await graph.get_task_history("Port the 2025 site template"))[0]
    assert detail.created_in is not None
    assert detail.created_in.date == detail.first_seen
    assert detail.created_in.source_ref.endswith("#section-4")
    assert detail.note_file.endswith(".md")
    assert detail.extraction_mode in {"markdown", "llm"}
    assert detail.identity_basis == "workgroup_description"


async def test_same_description_returns_two_distinct_tasks(graph):
    details = await graph.get_task_history("Send the reminder email", limit=5)
    assert len(details) == 2
    assert len({d.id for d in details}) == 2
    assert {d.workgroup for d in details} == {"communications", "program"}
    assert {d.owners[0] for d in details} == {"Sanjana Iyer", "Devika Nair"}


async def test_explicit_ids_keep_two_identical_items_apart(graph):
    details = await graph.get_task_history("Follow up with the sponsor leads", limit=5)
    assert len(details) == 2
    assert all(d.identity_basis == "explicit_id" for d in details)
    assert sorted(len(d.owners) for d in details) == [0, 1]


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


async def test_person_context_separates_membership_from_interest(graph):
    # Rehan is on both workgroups he asked for: Sponsorship from the meeting
    # notes, Finance from his application. Nothing is outstanding for him.
    assigned = await graph.get_person_context("Rehan Mathew")
    assert assigned.is_volunteer
    assert set(assigned.member_of) == {"Sponsorship", "Finance"}
    assert assigned.awaiting_assignment_in == []

    # Lakshmi applied and has not been placed. That gap is the point of the field.
    waiting = await graph.get_person_context("Lakshmi Menon")
    assert waiting.member_of == []
    assert set(waiting.awaiting_assignment_in) == {"Volunteers", "Program & CFP"}
    assert waiting.open_tasks == []


async def test_membership_records_which_source_created_it(graph):
    context = await graph.get_workgroup_context("finance")
    assert any("via volunteer_application" in member for member in context.members)
    notes = await graph.get_workgroup_context("program")
    assert all("via meeting_notes" in member for member in notes.members)


async def test_partial_names_resolve_to_one_person(graph):
    assert (await graph.get_person_context("Lakshmi")).name == "Lakshmi Menon"


async def test_workgroup_context_is_one_call_for_where_are_we(graph):
    context = await graph.get_workgroup_context("Website & Tech")
    assert context.slug == "website-tech"
    assert context.members
    assert context.open_tasks
    assert context.recent_meetings
    assert any("2025 template" in d.statement for d in context.recent_decisions)


async def test_an_empty_workgroup_is_visible_rather_than_missing(graph):
    context = await graph.get_workgroup_context("community-partners")
    assert context is not None
    assert context.members == []
    assert context.open_tasks == []


async def test_interested_unassigned_excludes_declined_applicants(graph):
    waiting = await graph.find_interested_unassigned_volunteers()
    names = {v.name for v in waiting}
    assert "Vikram Chandrasekaran" not in names, "declined applications are not a pipeline"
    assert "Lakshmi Menon" in names


async def test_unknown_names_return_nothing_rather_than_guessing(graph):
    assert await graph.get_person_context("Nobody McNobody") is None
    assert await graph.get_workgroup_context("quidditch") is None
    assert await graph.get_meeting_context(meeting_id=999999) is None
