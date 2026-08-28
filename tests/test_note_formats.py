"""The authoring contract: the same meeting, in both representations.

A Google Doc reaches the pipeline as two different things. Download it by hand
and you get Markdown, with `##` headings and `**bold**` labels. Read it through
CocoIndex's Google Drive connector and you get plain text, where the headings
are ordinary short lines and the bold is gone.

These tests parse both files and assert the results are identical, because if
they ever diverge the graph quietly changes shape depending on how the notes
arrived. `docs/meeting-notes-template.md` is the document these fixtures are
built from.
"""

from pathlib import Path

import pytest

from scipy_india_kg.extraction import extract_meeting_markdown, split_meetings
from scipy_india_kg.task_identity import task_identity

FORMATS = Path(__file__).resolve().parent / "fixtures" / "note_formats"
MARKDOWN = FORMATS / "template-drive-markdown.md"
PLAINTEXT = FORMATS / "template-drive-plaintext.txt"


def parse(path: Path, registry):
    sections = split_meetings(path.read_text(encoding="utf-8"))
    return [m for m in (extract_meeting_markdown(s, registry) for s in sections) if m]


@pytest.fixture(params=[MARKDOWN, PLAINTEXT], ids=["markdown", "plaintext"])
def meetings(request, registry):
    return parse(request.param, registry)


# --------------------------------------------------------------------------- #
# The two representations must agree
# --------------------------------------------------------------------------- #


def test_both_exports_parse_to_the_same_thing(registry):
    markdown = [m.model_dump(mode="json") for m in parse(MARKDOWN, registry)]
    plaintext = [m.model_dump(mode="json") for m in parse(PLAINTEXT, registry)]
    assert markdown == plaintext


def test_the_document_title_is_not_mistaken_for_a_meeting(registry):
    for path in (MARKDOWN, PLAINTEXT):
        sections = split_meetings(path.read_text(encoding="utf-8"))
        assert "SciPy India 2026 meeting notes" in sections[0]
        assert extract_meeting_markdown(sections[0], registry) is None


# --------------------------------------------------------------------------- #
# The template's own fields
# --------------------------------------------------------------------------- #


def test_meeting_line_supplies_the_date_and_title(meetings):
    assert [str(m.date) for m in meetings] == ["2026-09-05", "2026-09-12"]
    assert meetings[0].title == "Volunteer onboarding"
    assert meetings[1].title == "Website and CFP follow-up"


def test_facilitator_is_not_repeated_in_attendees(meetings):
    first = meetings[0]
    assert first.organizer.name == "Priya Vasudevan"
    assert [p.name for p in first.attendees] == [
        "Meera Raghavan",
        "Kabir Anand",
        "Sanjana Iyer",
    ]


def test_workgroups_resolve_through_the_registry(meetings):
    assert set(meetings[0].workgroups) >= {"registration-help-desk", "website", "program-committee"}


def test_topics_and_decisions_are_read_as_prose(meetings):
    first = meetings[0]
    assert len(first.topics) == 3
    assert first.topics[0].startswith("Volunteer applications received")
    assert len(first.decisions) == 2
    # A decision wrapped across two source lines comes back as one sentence.
    assert first.decisions[0].statement.endswith("assigning new applicants to a workgroup.")


def test_task_blocks_carry_every_field(meetings):
    tasks = {t.description: t for t in meetings[0].tasks}
    intro = tasks["Schedule intro calls with the shortlisted volunteers"]
    assert intro.explicit_id == "intro-calls"
    assert intro.workgroup == "registration-help-desk"
    assert [o.name for o in intro.owners] == ["Priya Vasudevan"]
    assert intro.status == "open"
    assert intro.due == "2026-09-10"


def test_a_blank_owner_means_unassigned_not_guessed(meetings):
    tasks = {t.description: t for t in meetings[0].tasks}
    reviewers = tasks["Recruit additional CFP reviewers"]
    assert reviewers.owners == []
    assert reviewers.due == ""
    assert reviewers.status == "open"


def test_notes_section_reaches_nothing(meetings):
    """Its prose must not be read as a decision."""
    statements = " ".join(d.statement for d in meetings[0].decisions)
    assert "Revisit assignments" not in statements
    assert "more interest in Program & CFP" not in statements


# --------------------------------------------------------------------------- #
# The reason IDs exist
# --------------------------------------------------------------------------- #


def test_a_repeated_id_keeps_one_task_across_meetings(meetings):
    note_file = "notes.md"
    first = next(t for t in meetings[0].tasks if t.explicit_id == "website-holding-page")
    second = next(t for t in meetings[1].tasks if t.explicit_id == "website-holding-page")
    assert first.status == "in_progress"
    assert second.status == "done"

    def key(task):
        return task_identity(
            note_file=note_file,
            description=task.description,
            workgroup=task.workgroup,
            explicit_id=task.explicit_id,
        ).id

    assert key(first) == key(second)


def test_an_id_survives_a_rewording(meetings):
    """The second meeting could have reworded the task and kept its history."""
    original = next(t for t in meetings[0].tasks if t.explicit_id == "cfp-reviewer-recruitment")
    reworded_id = task_identity(
        note_file="notes.md",
        description="Find more people to review CFP submissions",
        workgroup="program-committee",
        explicit_id="cfp-reviewer-recruitment",
    ).id
    assert (
        task_identity(
            note_file="notes.md",
            description=original.description,
            workgroup=original.workgroup,
            explicit_id=original.explicit_id,
        ).id
        == reworded_id
    )


def test_an_owner_appearing_later_is_recorded(meetings):
    """The reviewer task starts unowned and gains Devika Nair in the second meeting."""
    later = next(t for t in meetings[1].tasks if t.explicit_id == "cfp-reviewer-recruitment")
    assert [o.name for o in later.owners] == ["Devika Nair"]
    assert later.status == "in_progress"


# --------------------------------------------------------------------------- #
# Deviations a human will actually produce
# --------------------------------------------------------------------------- #

BASE = """Meeting: 2026-10-01 | Ordinary meeting

Facilitator: Meera Raghavan
Attendees: Kabir Anand

Topics

Something we talked about.

Action items

Task: Do the thing
Workgroup: Website & Tech
Owner: Kabir Anand
Status: open
"""


def test_a_missing_topics_section_is_fine(registry):
    text = BASE.replace("Topics\n\nSomething we talked about.\n\n", "")
    meeting = extract_meeting_markdown(text, registry)
    assert meeting.topics == []
    assert len(meeting.tasks) == 1


def test_an_extra_notes_paragraph_is_fine(registry):
    text = BASE + "\nNotes\n\nWe ran over by ten minutes and will pick this up next time.\n"
    meeting = extract_meeting_markdown(text, registry)
    assert len(meeting.tasks) == 1
    assert meeting.decisions == []


def test_a_meeting_with_no_action_items_is_fine(registry):
    text = BASE[: BASE.index("Action items")]
    meeting = extract_meeting_markdown(text, registry)
    assert meeting.tasks == []
    assert meeting.topics == ["Something we talked about."]


def test_field_order_inside_a_task_block_does_not_matter(registry):
    shuffled = BASE.replace(
        "Task: Do the thing\nWorkgroup: Website & Tech\nOwner: Kabir Anand\nStatus: open",
        "Task: Do the thing\nStatus: open\nOwner: Kabir Anand\nWorkgroup: Website & Tech",
    )
    assert (
        extract_meeting_markdown(shuffled, registry).tasks
        == extract_meeting_markdown(BASE, registry).tasks
    )


def test_leftover_bold_markup_does_not_break_labels(registry):
    text = BASE.replace("Facilitator:", "**Facilitator:**").replace("Owner:", "**Owner:**")
    meeting = extract_meeting_markdown(text, registry)
    assert meeting.organizer.name == "Meera Raghavan"
    assert [o.name for o in meeting.tasks[0].owners] == ["Kabir Anand"]


def test_a_meeting_without_an_iso_date_is_skipped(registry):
    section = "Meeting: 5 September | No ISO date\n\nTopics\n\nX."
    assert extract_meeting_markdown(section, registry) is None


# --------------------------------------------------------------------------- #
# Edge cases a real Google Doc produces
#
# The deterministic parser promises correctness for the documented template, not
# for arbitrary prose. These are the deviations a person editing in Google Docs
# will produce anyway, so the parser has to survive them.
# --------------------------------------------------------------------------- #


def test_google_docs_bullet_characters(registry):
    """Docs turns list items into • or ● and an export keeps the glyph."""
    section = (
        "Meeting: 2026-11-01 | Bulleted export\n\n"
        "Facilitator: Meera Raghavan\n\n"
        "Topics\n\n"
        "● First topic.\n"
        "• Second topic.\n"
        "▪ Third topic.\n"
    )
    meeting = extract_meeting_markdown(section, registry)
    assert meeting.topics == ["First topic.", "Second topic.", "Third topic."]


def test_a_wrapped_task_description_stays_one_task(registry):
    """Docs wraps long lines. The continuation must join the description rather
    than being dropped or read as a new item."""
    section = (
        "Meeting: 2026-11-01 | Wrapping\n\n"
        "Action items\n\n"
        "Task: Draft the sponsor prospectus and circulate it to the\n"
        "organizing list before the next call\n"
        "Owner: Rehan Mathew\n"
        "Workgroup: Sponsorship\n"
    )
    task = extract_meeting_markdown(section, registry).tasks[0]
    assert task.description == (
        "Draft the sponsor prospectus and circulate it to the organizing list before the next call"
    )
    assert [o.name for o in task.owners] == ["Rehan Mathew"]


def test_an_abbreviation_does_not_split_a_decision(registry):
    """`e.g.` ends in a full stop without ending the sentence."""
    section = (
        "Meeting: 2026-11-01 | Abbreviations\n\n"
        "Decisions\n\n"
        "We will accept short-form submissions, e.g.\n"
        "lightning talks and posters, from the second week.\n"
    )
    decisions = extract_meeting_markdown(section, registry).decisions
    assert len(decisions) == 1
    assert decisions[0].statement.endswith("from the second week.")


def test_a_url_does_not_split_a_topic(registry):
    """A wrapped line ending in a domain looks like a sentence end but is not."""
    section = (
        "Meeting: 2026-11-01 | Links\n\n"
        "Topics\n\n"
        "Review the ticketing options listed at https://example.invalid\n"
        "before the next call.\n"
        "Second topic.\n"
    )
    topics = extract_meeting_markdown(section, registry).topics
    assert topics == [
        "Review the ticketing options listed at https://example.invalid before the next call.",
        "Second topic.",
    ]


def test_a_decision_containing_a_colon_is_read_whole(registry):
    section = (
        "Meeting: 2026-11-01 | Colons\n\n"
        "Decisions\n\n"
        "Three sponsor tiers: platinum, gold and community.\n"
    )
    decisions = extract_meeting_markdown(section, registry).decisions
    assert len(decisions) == 1
    assert decisions[0].statement == "Three sponsor tiers: platinum, gold and community."


def test_two_meetings_on_one_date_stay_separate(registry):
    text = (
        "Meeting: 2026-11-01 | Morning session\n\n"
        "Facilitator: Meera Raghavan\n\n"
        "Action items\n\n"
        "Task: Book the room\n"
        "Workgroup: Venue & Logistics\n\n"
        "Meeting: 2026-11-01 | Afternoon session\n\n"
        "Facilitator: Devika Nair\n\n"
        "Action items\n\n"
        "Task: Send the agenda\n"
        "Workgroup: Program & CFP\n"
    )
    meetings = [
        m for m in (extract_meeting_markdown(s, registry) for s in split_meetings(text)) if m
    ]
    assert len(meetings) == 2
    assert [m.title for m in meetings] == ["Morning session", "Afternoon session"]
    assert meetings[0].organizer.name == "Meera Raghavan"
    assert meetings[1].organizer.name == "Devika Nair"


def test_an_unknown_section_is_ignored_not_misread(registry):
    """A heading the parser does not recognise must not have its contents read
    as decisions or action items."""
    section = (
        "Meeting: 2026-11-01 | Unknown sections\n\n"
        "Apologies\n\n"
        "Kabir Anand could not make it and will catch up offline.\n\n"
        "Decisions\n\n"
        "The CFP closes on 5 April.\n"
    )
    meeting = extract_meeting_markdown(section, registry)
    assert [d.statement for d in meeting.decisions] == ["The CFP closes on 5 April."]
    assert meeting.tasks == []
