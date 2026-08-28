"""Task identity: recurrence must keep working, collisions must not merge."""

import pytest

from scipy_india_kg.extraction import extract_meeting_markdown, split_meetings
from scipy_india_kg.task_identity import normalize_description, task_identity

NOTE = "notes.md"


def key(description, workgroup=None, explicit_id=None, note_file=NOTE):
    return task_identity(
        note_file=note_file,
        description=description,
        workgroup=workgroup,
        explicit_id=explicit_id,
    )


# --------------------------------------------------------------------------- #
# Recurrence: the behaviour that must survive
# --------------------------------------------------------------------------- #


def test_the_same_item_in_a_later_meeting_is_the_same_task():
    first = key("Port the 2025 site template", "website")
    later = key("Port the 2025 site template", "website")
    assert first.id == later.id


def test_punctuation_and_case_do_not_split_a_task():
    assert (
        key("Draft the CFP timeline", "program-committee").id
        == key("draft the CFP timeline.", "program-committee").id
    )
    assert normalize_description("  Draft  the CFP timeline. ") == "draft the cfp timeline"


# --------------------------------------------------------------------------- #
# Collisions: the behaviour that was missing
# --------------------------------------------------------------------------- #


def test_same_description_in_different_workgroups_stays_two_tasks():
    comms = key("Send the reminder email", "social-media-communications")
    program = key("Send the reminder email", "program-committee")
    assert comms.id != program.id
    assert comms.scope == "social-media-communications"
    assert program.scope == "program-committee"


def test_same_description_in_different_documents_stays_two_tasks():
    this_year = key("Book the venue", "logistics", note_file="2026.md")
    last_year = key("Book the venue", "logistics", note_file="2025.md")
    assert this_year.id != last_year.id


def test_an_explicit_id_separates_two_identical_items_in_one_workgroup():
    platinum = key("Follow up with the sponsor leads", "sponsoring", "sponsor-followup-platinum")
    community = key("Follow up with the sponsor leads", "sponsoring", "sponsor-followup-community")
    assert platinum.id != community.id
    assert platinum.basis == community.basis == "explicit_id"


def test_an_explicit_id_survives_a_reworded_description():
    """The point of an id: the task keeps its identity when the wording changes."""
    before = key("Follow up with sponsors", "sponsoring", "sponsor-followup-platinum")
    after = key("Chase the platinum sponsor leads again", "sponsoring", "sponsor-followup-platinum")
    assert before.id == after.id


def test_without_a_workgroup_identity_falls_back_to_description():
    unscoped = key("Send the reminder email")
    assert unscoped.basis == "description"
    assert unscoped.scope == "unscoped"
    assert unscoped.id != key("Send the reminder email", "program-committee").id


@pytest.mark.parametrize(
    "description",
    ["Send the reminder email", "Book the room", "Follow up", "Update the website"],
)
def test_identity_is_deterministic_across_runs(description):
    assert key(description, "program-committee").id == key(description, "program-committee").id


def test_ids_are_readable_enough_to_recognise():
    identity = key("Recruit four more CFP reviewers", "program-committee")
    assert identity.id.startswith("program-committee:recruit-four-more-cfp")


# --------------------------------------------------------------------------- #
# End to end through the extractor
# --------------------------------------------------------------------------- #


def sections(notes_text, registry):
    parsed = [extract_meeting_markdown(s, registry) for s in split_meetings(notes_text)]
    return [m for m in parsed if m is not None]


def test_fixture_carries_a_same_description_collision(notes_text, registry):
    tasks = [t for m in sections(notes_text, registry) for t in m.tasks]
    reminders = [t for t in tasks if t.description == "Send the reminder email"]
    assert len(reminders) == 2
    assert {t.workgroup for t in reminders} == {"social-media-communications", "program-committee"}
    ids = {key(t.description, t.workgroup).id for t in reminders}
    assert len(ids) == 2


def test_fixture_carries_an_explicit_id_case(notes_text, registry):
    """The demo gives these two distinguishable wording, because two identical
    rows in the dashboard read as a bug. The IDs are what actually keep them
    apart, and the pathological same-wording case lives in the tests above."""
    tasks = [t for m in sections(notes_text, registry) for t in m.tasks]
    followups = [t for t in tasks if t.description.startswith("Follow up with the")]
    assert len(followups) == 2
    assert {t.explicit_id for t in followups} == {
        "sponsor-followup-platinum",
        "sponsor-followup-community",
    }


def test_the_extractor_reads_an_explicit_id_without_eating_the_description(registry):
    section = (
        "2026-04-01 — Test\n\n### Action items\n"
        "- [ ] Chase the caterer — id: caterer-chase — owner: Sam Lee "
        "— workgroup: venue-logistics\n"
    )
    task = extract_meeting_markdown(section, registry).tasks[0]
    assert task.description == "Chase the caterer"
    assert task.explicit_id == "caterer-chase"
    assert [o.name for o in task.owners] == ["Sam Lee"]
