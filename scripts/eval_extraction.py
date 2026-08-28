#!/usr/bin/env python3
"""Evaluate the LLM extraction path against the deterministic one.

The Markdown extractor is well tested; the LLM extractor is the one that will
run against real minutes, and it has never been exercised here because this
environment has no API credentials. This script is how you check it when you do.

Two modes, because the two documents you want to test on are different shapes:

**--compare** runs both extractors over the *same* lightly structured document
and diffs them. The Markdown parse is ground truth, so every difference is an
LLM error you can name: a meeting it missed, a decision it invented, an owner
nobody wrote down, a status it guessed, a workgroup it misfiled.

**--ground** runs only the LLM extractor and audits every field against the
source text. Use this on real prose minutes, where there is no deterministic
baseline to diff against. It cannot tell you what the model *missed*, but it
catches the failure that matters most: things the model made up. Every owner
name, deadline and workgroup is checked for support in the section it came from.

Person resolution is compared separately with --resolution, which runs the
exact and embedding resolvers over the same name set and reports names that one
merged and the other did not.

    # against the project's own fixture, where both extractors can parse
    export OPENAI_API_KEY=...
    python scripts/eval_extraction.py --compare data/meeting_notes/scipy-india-2026-meeting-notes.md

    # against real prose minutes, e.g. the PyConf Hyderabad notes
    python scripts/eval_extraction.py --ground ~/Downloads/"PyConf Hyderabad 2025 Meeting Notes.md"

    # person resolution only (embedding needs an API key for the pair resolver)
    python scripts/eval_extraction.py --resolution data/meeting_notes/*.md

Nothing here writes to Neo4j and nothing here is committed as a test: it costs
money to run and its results are a judgement call, not a pass/fail.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from scipy_india_kg.extraction import (  # noqa: E402
    extract_meeting_llm,
    extract_meeting_markdown,
    split_meetings,
)
from scipy_india_kg.models import ExtractedMeeting  # noqa: E402
from scipy_india_kg.person_resolution import normalize_name, resolve_exact  # noqa: E402
from scipy_india_kg.task_identity import normalize_description  # noqa: E402
from scipy_india_kg.workgroups import default_registry  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Findings:
    """Named after the failure modes worth looking for, not after metrics."""

    missed_meetings: list[str] = field(default_factory=list)
    extra_meetings: list[str] = field(default_factory=list)
    wrong_dates: list[str] = field(default_factory=list)
    missed_tasks: list[str] = field(default_factory=list)
    invented_tasks: list[str] = field(default_factory=list)
    invented_owners: list[str] = field(default_factory=list)
    missed_owners: list[str] = field(default_factory=list)
    invented_statuses: list[str] = field(default_factory=list)
    invented_deadlines: list[str] = field(default_factory=list)
    workgroup_mismatches: list[str] = field(default_factory=list)
    invented_decisions: list[str] = field(default_factory=list)
    missed_decisions: list[str] = field(default_factory=list)
    unsupported_attendees: list[str] = field(default_factory=list)

    def total(self) -> int:
        return sum(len(getattr(self, f.name)) for f in self.__dataclass_fields__.values())

    def report(self) -> str:
        lines = []
        for name in self.__dataclass_fields__:
            entries = getattr(self, name)
            if not entries:
                continue
            lines.append(f"\n{name.replace('_', ' ').upper()} ({len(entries)})")
            lines.extend(f"  - {entry}" for entry in entries)
        return "\n".join(lines) if lines else "\nNothing flagged."


def _names_in(text: str) -> set[str]:
    """Normalised word bigrams and unigrams, for checking a name appears at all."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-.]*", text)
    tokens = {normalize_name(word) for word in words}
    tokens |= {normalize_name(f"{a} {b}") for a, b in zip(words, words[1:], strict=False)}
    tokens |= {
        normalize_name(f"{a} {b} {c}") for a, b, c in zip(words, words[1:], words[2:], strict=False)
    }
    return {token for token in tokens if token}


def _supported(name: str, section: str) -> bool:
    """Is this person named in the section, allowing for a surname-only mention?"""
    normalized = normalize_name(name)
    if not normalized:
        return False
    haystack = _names_in(section)
    if normalized in haystack:
        return True
    return all(part in haystack for part in normalized.split())


# --------------------------------------------------------------------------- #
# Grounding audit: does the source support what the model returned?
# --------------------------------------------------------------------------- #


def audit_grounding(section: str, meeting: ExtractedMeeting, findings: Findings) -> None:
    where = f"{meeting.date} {meeting.title[:40]}"
    lowered = section.lower()

    if meeting.organizer and not _supported(meeting.organizer.name, section):
        findings.invented_owners.append(
            f"{where}: facilitator {meeting.organizer.name!r} not in the text"
        )
    for person in meeting.attendees:
        if not _supported(person.name, section):
            findings.unsupported_attendees.append(
                f"{where}: attendee {person.name!r} not in the text"
            )

    for task in meeting.tasks:
        head = normalize_description(task.description)[:40]
        for owner in task.owners:
            if not _supported(owner.name, section):
                findings.invented_owners.append(
                    f"{where}: {head!r} owned by {owner.name!r}, not in the text"
                )
        if task.status not in {"unknown", "open"} and task.status.replace("_", " ") not in lowered:
            # A non-default status should be traceable to a word in the notes.
            markers = {
                "done": ("done", "complete", "✅", "🟢"),
                "blocked": ("block", "stuck"),
                "in_progress": ("progress", "wip", "underway", "ongoing"),
                "dropped": ("drop", "cancel", "abandon"),
            }
            if not any(marker in lowered for marker in markers.get(task.status, ())):
                findings.invented_statuses.append(
                    f"{where}: {head!r} marked {task.status} with no support"
                )
        if task.due and task.due.lower() not in lowered:
            findings.invented_deadlines.append(
                f"{where}: {head!r} due {task.due!r}, not in the text"
            )

    for decision in meeting.decisions:
        # A decision should share meaningful vocabulary with its section.
        words = [w for w in re.findall(r"[a-z]{5,}", decision.statement.lower())]
        if words and sum(word in lowered for word in words) < max(1, len(words) // 3):
            findings.invented_decisions.append(
                f"{where}: decision {decision.statement[:70]!r} looks unsupported"
            )


# --------------------------------------------------------------------------- #
# Comparison against the deterministic baseline
# --------------------------------------------------------------------------- #


def compare(baseline: ExtractedMeeting, candidate: ExtractedMeeting, findings: Findings) -> None:
    where = str(baseline.date)
    if baseline.date != candidate.date:
        findings.wrong_dates.append(f"{where}: LLM read the date as {candidate.date}")

    base_tasks = {normalize_description(t.description): t for t in baseline.tasks}
    cand_tasks = {normalize_description(t.description): t for t in candidate.tasks}

    for key, task in base_tasks.items():
        if key not in cand_tasks and not any(key in other for other in cand_tasks):
            findings.missed_tasks.append(f"{where}: {task.description[:60]!r}")
    for key, task in cand_tasks.items():
        if key not in base_tasks and not any(key in other for other in base_tasks):
            findings.invented_tasks.append(f"{where}: {task.description[:60]!r}")

    for key, task in base_tasks.items():
        other = cand_tasks.get(key)
        if other is None:
            continue
        base_owners = {normalize_name(o.name) for o in task.owners}
        cand_owners = {normalize_name(o.name) for o in other.owners}
        for extra in cand_owners - base_owners:
            findings.invented_owners.append(
                f"{where}: {task.description[:40]!r} gained owner {extra!r}"
            )
        for missing in base_owners - cand_owners:
            findings.missed_owners.append(
                f"{where}: {task.description[:40]!r} lost owner {missing!r}"
            )
        if task.status != other.status:
            findings.invented_statuses.append(
                f"{where}: {task.description[:40]!r} {task.status} -> {other.status}"
            )
        if task.due != other.due:
            findings.invented_deadlines.append(
                f"{where}: {task.description[:40]!r} due {task.due!r} -> {other.due!r}"
            )
        if task.workgroup != other.workgroup:
            findings.workgroup_mismatches.append(
                f"{where}: {task.description[:40]!r} {task.workgroup} -> {other.workgroup}"
            )

    base_decisions = {normalize_description(d.statement)[:60] for d in baseline.decisions}
    cand_decisions = {normalize_description(d.statement)[:60] for d in candidate.decisions}
    for missing in base_decisions - cand_decisions:
        findings.missed_decisions.append(f"{where}: {missing!r}")
    for extra in cand_decisions - base_decisions:
        findings.invented_decisions.append(f"{where}: {extra!r}")


# --------------------------------------------------------------------------- #
# Person resolution
# --------------------------------------------------------------------------- #


async def compare_resolution(names: set[str]) -> str:
    exact = resolve_exact(names)
    lines = [f"{len(names)} raw names -> {len(exact.canonicals())} canonical under `exact`"]

    model = os.environ.get("RESOLUTION_LLM_MODEL", "openai/gpt-5-mini")
    if not os.environ.get("OPENAI_API_KEY"):
        lines.append(
            "\nSkipping the embedding resolver: it needs an API key for the LLM pair "
            "confirmation step. Set OPENAI_API_KEY (or RESOLUTION_LLM_MODEL's provider key)."
        )
        return "\n".join(lines)

    from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder

    from scipy_india_kg.person_resolution import resolve_embedding

    embedding = await resolve_embedding(
        names, SentenceTransformerEmbedder("Snowflake/snowflake-arctic-embed-xs"), model
    )
    lines.append(
        f"{len(names)} raw names -> {len(embedding.canonicals())} canonical under `embedding`"
    )

    exact_groups = {frozenset(group) for group in exact.groups().values()}
    embedding_groups = {frozenset(group) for group in embedding.groups().values()}
    merged = [sorted(group) for group in embedding_groups - exact_groups if len(group) > 1]
    split = [sorted(group) for group in exact_groups - embedding_groups if len(group) > 1]
    if merged:
        lines.append("\nMERGED BY EMBEDDING ONLY (check for wrong merges):")
        lines.extend(f"  - {group}" for group in merged)
    if split:
        lines.append("\nKEPT APART BY EMBEDDING (check for missed merges):")
        lines.extend(f"  - {group}" for group in split)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #


async def run(args: argparse.Namespace) -> int:
    registry = default_registry()
    text = args.document.read_text(encoding="utf-8")
    sections = split_meetings(text)
    print(f"{args.document.name}: {len(sections)} sections")

    if args.resolution:
        names: set[str] = set()
        for section in sections:
            meeting = extract_meeting_markdown(section, registry)
            if meeting is None:
                continue
            if meeting.organizer:
                names.add(meeting.organizer.name)
            names.update(p.name for p in meeting.attendees)
            for task in meeting.tasks:
                names.update(o.name for o in task.owners)
        print(await compare_resolution(names))
        return 0

    model = os.environ.get("LLM_MODEL", "openai/gpt-5-mini")
    if not any(
        os.environ.get(key) for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")
    ):
        print(
            "\nNo LLM credentials in the environment. Set OPENAI_API_KEY (or whichever "
            f"provider {model} needs) and re-run. Nothing was called.",
            file=sys.stderr,
        )
        return 2

    findings = Findings()
    extracted: list[dict[str, Any]] = []

    for index, section in enumerate(sections):
        baseline = extract_meeting_markdown(section, registry)
        if args.compare and baseline is None:
            continue  # not a meeting under the deterministic parse either

        candidate = await extract_meeting_llm(section, registry, model)
        if candidate is None:
            if baseline is not None:
                findings.missed_meetings.append(
                    f"section {index}: {baseline.date} {baseline.title}"
                )
            continue
        if args.compare and baseline is None:
            findings.extra_meetings.append(f"section {index}: LLM invented {candidate.date}")
            continue

        print(f"  section {index}: {candidate.date} {candidate.title[:50]}")
        extracted.append(candidate.model_dump(mode="json"))
        audit_grounding(section, candidate, findings)
        if args.compare and baseline is not None:
            compare(baseline, candidate, findings)

    print(f"\n{'=' * 70}\n{findings.total()} findings across {len(extracted)} meetings")
    print(findings.report())

    if args.out:
        args.out.write_text(
            json.dumps({"meetings": extracted, "findings": findings.__dict__}, indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("document", type=Path, help="a Markdown meeting-notes document")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--compare", action="store_true", help="diff the LLM against the Markdown parse"
    )
    mode.add_argument(
        "--ground", action="store_true", help="audit LLM output against the source text"
    )
    mode.add_argument("--resolution", action="store_true", help="compare person resolvers only")
    parser.add_argument("--out", type=Path, default=None, help="write the full result as JSON")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
