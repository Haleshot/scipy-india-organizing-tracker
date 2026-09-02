"""The Docs-formatted notes must parse to exactly the same meetings.

`scripts/format_for_docs.py` adds headings, bold labels and bullets so the Google
Doc is readable during a call. None of that reaches the pipeline, because Drive
exports a Doc as plain text. This proves the formatting is cosmetic by parsing
both versions and comparing what comes out.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from scipy_india_kg.extraction import extract_meeting_markdown, split_meetings

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTES = REPO_ROOT / "data" / "meeting_notes" / "scipy-india-2026-meeting-notes.md"


def _load_formatter():
    path = REPO_ROOT / "scripts" / "format_for_docs.py"
    spec = importlib.util.spec_from_file_location("format_for_docs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as_google_docs_plain_text(markdown: str) -> str:
    """What Drive hands back after a Doc built from this Markdown is exported.

    Google Docs turns `##` into a heading and `**` into bold on paste, and the
    plain-text export then drops both, leaving the words. Bullets survive as a
    leading dash, which the parser already tolerates.
    """
    lines = []
    for line in markdown.splitlines():
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = line.replace("**", "")
        if line.strip() == "---":
            continue
        lines.append(line)
    return "\n".join(lines)


def _meetings(text: str, registry):
    out = []
    for section in split_meetings(text):
        meeting = extract_meeting_markdown(section, registry)
        if meeting is not None:
            out.append(meeting)
    return out


def test_formatting_does_not_change_what_the_pipeline_reads(registry):
    plain = NOTES.read_text(encoding="utf-8")
    formatted = _load_formatter().format_notes(plain)
    exported = _as_google_docs_plain_text(formatted)

    before = _meetings(plain, registry)
    after = _meetings(exported, registry)

    assert before, "the notes should contain meetings to compare"
    assert len(after) == len(before)
    for original, roundtripped in zip(before, after, strict=True):
        assert roundtripped.date == original.date
        assert roundtripped.title == original.title
        assert roundtripped.attendees == original.attendees
        assert roundtripped.organizer == original.organizer
        assert [t.description for t in roundtripped.tasks] == [
            t.description for t in original.tasks
        ]
        assert [t.status for t in roundtripped.tasks] == [t.status for t in original.tasks]
        assert [t.explicit_id for t in roundtripped.tasks] == [
            t.explicit_id for t in original.tasks
        ]
        assert [t.issue_refs for t in roundtripped.tasks] == [t.issue_refs for t in original.tasks]
        assert [d.statement for d in roundtripped.decisions] == [
            d.statement for d in original.decisions
        ]
        assert roundtripped.workgroups == original.workgroups
