#!/usr/bin/env python3
"""Turn the plain notes into something worth pasting into a Google Doc.

The pipeline reads Docs as plain text, so headings and bold are invisible to it.
They are not invisible to the people who read the document during a call, and a
wall of same-sized text is hard to scan when somebody asks what we decided in
July.

So this adds structure for humans and changes nothing the parser sees. Google
Docs converts Markdown on paste when Tools, Preferences, "Automatically detect
Markdown" is on, which turns `##` into a real heading and `**` into bold.

    python scripts/format_for_docs.py            # print it
    python scripts/format_for_docs.py -o out.md  # write it

tests/test_docs_format.py parses both versions and asserts they produce the same
meetings, so this cannot drift into changing the content.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_NOTES = REPO_ROOT / "data" / "meeting_notes" / "scipy-india-2026-meeting-notes.md"

# Labels that open a field. Bolding the label and leaving the value alone keeps
# the line scannable without touching what the parser matches on.
FIELD_LABELS = (
    "Facilitator",
    "Attendees",
    "Workgroups",
    "Task",
    "ID",
    "Workgroup",
    "Owner",
    "Owners",
    "Status",
    "Due",
    "Issue",
    "Issues",
)

SECTION_HEADINGS = (
    "Topics",
    "Decisions",
    "Action items",
    "Workgroup changes",
    "Notes",
    "Links",
)


def format_notes(text: str) -> str:
    out: list[str] = []
    in_action_items = False

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            out.append("")
            continue

        # The document title.
        if not out and not stripped.startswith(("Meeting:", "#")):
            out.append(f"# {stripped}")
            continue

        # A meeting opens a new section, and gets the biggest heading under the
        # title so the Doc's own outline pane becomes a list of meetings.
        if stripped.startswith("Meeting:"):
            out.append("")
            out.append("---")
            out.append("")
            out.append(f"## {stripped}")
            in_action_items = False
            continue

        if stripped in SECTION_HEADINGS:
            out.append(f"### {stripped}")
            in_action_items = stripped == "Action items"
            continue

        label, sep, value = stripped.partition(":")
        if sep and label in FIELD_LABELS:
            # A Task: line starts a new item, so it gets a bullet and the ones
            # under it get indented. Everything else is a plain bold label.
            if label == "Task":
                out.append(f"- **{label}:**{(' ' + value.strip()) if value.strip() else ''}")
            elif in_action_items:
                out.append(f"    - **{label}:**{(' ' + value.strip()) if value.strip() else ''}")
            else:
                out.append(f"**{label}:**{(' ' + value.strip()) if value.strip() else ''}")
            continue

        out.append(stripped)

    # Collapse the runs of blank lines the inserted rules leave behind.
    cleaned: list[str] = []
    for line in out:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notes", nargs="?", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    if not args.notes.is_file():
        print(f"error: {args.notes} does not exist", file=sys.stderr)
        return 1

    formatted = format_notes(args.notes.read_text(encoding="utf-8"))
    if args.output:
        args.output.write_text(formatted, encoding="utf-8")
        print(f"Wrote {args.output}")
        print("Paste it into the Doc with Tools, Preferences, Markdown detection on.")
    else:
        print(formatted, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
