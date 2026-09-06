"""Real Google Docs exports, kept because each one broke the parser.

tests/fixtures/exports/ holds documents exactly as Drive handed them back, not
documents written to be convenient. Every file here is a bug that reached the
published dashboard, and the point of the fixture is that it is not idealised:
the blank lines, the stray heading markers and the run-together labels are what
Docs actually produces.

Adding one: export the Doc, drop it in, assert what it should extract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scipy_india_kg.extraction import extract_meeting_markdown, split_meetings

EXPORTS = Path(__file__).resolve().parent / "fixtures" / "exports"


def _meetings(path: Path, registry):
    out = {}
    for section in split_meetings(path.read_text(encoding="utf-8")):
        meeting = extract_meeting_markdown(section, registry)
        if meeting is not None:
            out[str(meeting.date)] = meeting
    return out


@pytest.fixture(scope="module")
def headings_export():
    path = EXPORTS / "docs-headings-on-every-paragraph.md"
    assert path.is_file(), "the export fixture went missing"
    return path


def test_a_paragraph_styled_as_a_heading_is_still_a_paragraph(headings_export, registry):
    """Docs applies the surrounding paragraph style to a whole paste.

    Every body line of one meeting came back as "## ...", including the ones
    inside bullets. The meeting kept its title and lost its facilitator, its
    decisions and all ten of its action items.
    """
    meetings = _meetings(headings_export, registry)
    meeting = meetings["2026-09-06"]

    assert meeting.organizer is not None, "the facilitator line was styled as a heading"
    assert meeting.organizer.name == "Srihari Thyagarajan"
    assert len(meeting.decisions) == 4, "decision paragraphs were styled as headings"
    assert len(meeting.tasks) == 10


def test_blank_lines_between_bullets_do_not_split_a_task(headings_export, registry):
    """Docs puts a blank line between every bullet.

    A blank line used to close the open action item, so `ID:`, `Workgroup:`,
    `Owner:`, `Status:` and `Due:` each became a task of its own and ten items
    came back as sixty.
    """
    meeting = _meetings(headings_export, registry)["2026-09-06"]

    ids = [task.explicit_id for task in meeting.tasks]
    assert ids == [
        "volunteer-intro-call",
        "volunteer-call-time",
        "volunteer-shortlist",
        "volunteer-zulip-onboarding",
        "zulip-workgroup-channels",
        "sponsoring-volunteer-outreach",
        "indiafoss-booth",
        "indiafoss-collateral",
        "volunteer-startup-discount",
        "cfp-reviewing-questions",
    ]
    # Fields belong to their task rather than becoming tasks themselves.
    assert all(task.description for task in meeting.tasks)
    assert not any(
        task.description.startswith(("ID:", "Owner:", "Status:", "Due:")) for task in meeting.tasks
    )


def test_the_other_meetings_in_the_same_document_are_unaffected(headings_export, registry):
    """One badly pasted section must not disturb the ones around it."""
    meetings = _meetings(headings_export, registry)
    assert set(meetings) == {
        "2026-07-11",
        "2026-07-25",
        "2026-08-08",
        "2026-08-22",
        "2026-08-29",
        "2026-09-06",
    }
    assert len(meetings["2026-08-08"].tasks) == 6
    assert len(meetings["2026-08-29"].tasks) == 4
