"""Turning one meeting section of notes into an ``ExtractedMeeting``.

Two extractors, same output type:

``markdown``
    A deterministic parser for the labelled note format described in
    ``docs/meeting-notes-template.md``. No API key, no network, no
    non-determinism. This is what tests and the fixture demo run on, and it is
    also what a real Google Doc gets if the team writes to the template.

``llm``
    The upstream CocoIndex approach: instructor over LiteLLM with the same
    Pydantic schema. Use this when minutes are free prose and nobody is going to
    type ``Owner:`` by hand.

The deterministic parser reads two representations of the same document, because
a Google Doc reaches us as two different things depending on how it arrives. A
manual "download as Markdown" keeps ``##`` headings and ``-`` bullets; the
CocoIndex Google Drive connector exports Docs as plain text, where the headings
are just short lines and the bullets are gone. The template is built out of
plain labels (``Meeting:``, ``Facilitator:``, ``Task:``) precisely so that the
same document parses either way. ``tests/test_note_formats.py`` runs the same
meeting through both.

Both extractors are told the same thing: record what the section says and
nothing else. A missing owner stays missing, a missing status stays ``unknown``.
"""

from __future__ import annotations

import datetime
import re
from typing import cast

from .models import (
    TASK_STATUSES,
    ExtractedDecision,
    ExtractedMeeting,
    ExtractedPerson,
    ExtractedTask,
    ExtractedWorkgroupMove,
)
from .workgroups import WorkgroupRegistry

# A meeting starts either at a Markdown heading or at a `Meeting:` line. The
# second form is what survives a Google Doc export to plain text, where headings
# lose their `#` and become ordinary short lines.
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,2}\s+\S")
_MEETING_LINE_RE = re.compile(r"^\s{0,3}(?:#{1,3}\s*)?\*{0,2}meetings?\s*:", re.IGNORECASE)


def _is_boundary(line: str) -> bool:
    """Does this line start a new meeting section?

    A `###` heading does not: those are the subsections inside one meeting.
    """
    if _MEETING_LINE_RE.match(line):
        return True
    return bool(_MARKDOWN_HEADING_RE.match(line)) and not line.lstrip().startswith("###")


def split_meetings(text: str) -> list[str]:
    """Cut a notes document into one chunk per meeting.

    Everything before the first boundary is returned as its own chunk. It is
    normally the document title and a links list, and the extractor drops it for
    having no date.
    """
    sections: list[list[str]] = [[]]
    for line in text.splitlines():
        if _is_boundary(line):
            sections.append([])
        sections[-1].append(line)
    return [chunk for chunk in ("\n".join(lines).strip() for lines in sections) if chunk]


# ---------------------------------------------------------------------------
# Deterministic Markdown extractor
# ---------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
# Google Docs exports list items with the glyph it rendered, so a note that was
# a tidy `-` list in Markdown arrives as ●, • or ▪. All of them mean "bullet".
_BULLET_CHARS = r"-*+\u2022\u25cf\u25aa\u25e6\u2043\u00b7\u2219\u25a0\u25cb\u2010\u2013"
_BULLET_RE = re.compile(rf"^\s*[{_BULLET_CHARS}]\s+")
_CHECKBOX_RE = re.compile(rf"^\s*[{_BULLET_CHARS}]\s*\[( |x|X)\]\s*")
_FIELD_RE = re.compile(r"\b(owners?|workgroup|status|due|id|key)\s*:\s*", re.IGNORECASE)
_SUBHEADING_RE = re.compile(r"^#{3,}\s*(.+?)\s*$")
# In plain text a section heading is just a short line on its own: "Topics",
# "Decisions", "Action items". Recognised only when the whole line, stripped of
# any leftover markup, is one of the known section names, so a topic that
# happens to read "Decisions" would have to be that word alone to be mistaken
# for a heading.
_BARE_HEADING_RE = re.compile(r"^\s*\*{0,2}_{0,2}([A-Za-z][A-Za-z ]{2,30}?)_{0,2}\*{0,2}\s*:?\s*$")
_LABEL_RE = re.compile(
    r"^\s*\*{0,2}(facilitator|organizer|organiser|attendees|present|workgroups)\*{0,2}\s*:\s*(.*)$",
    re.IGNORECASE,
)
# A `Task:` line opens an action-item block; the fields that follow belong to it
# until the next `Task:` or the end of the section. An empty value means the
# notes did not record one, which is different from the field being absent and
# is treated the same way: nothing is inferred.
_TASK_OPEN_RE = re.compile(r"^\s*\*{0,2}task\*{0,2}\s*:\s*(.*)$", re.IGNORECASE)
_TASK_FIELD_RE = re.compile(
    r"^\s*\*{0,2}(id|key|owners?|workgroup|status|due)\*{0,2}\s*:\s*(.*)$", re.IGNORECASE
)
_PARENTHETICAL_WG_RE = re.compile(r"^\(([^)]+)\)\s*")
_JOINS_RE = re.compile(
    r"^(?P<person>.+?)\s+(?:joins|joined|moves to|assigned to)\s+(?P<wg>.+?)\.?$", re.IGNORECASE
)
_TRAILING_SEP = re.compile(r"[\s–—|,;:.-]+$")
_LEADING_SEP = re.compile(r"^[\s–—|,;:.-]+")

# Which `###` subsection a line belongs to. Anything unrecognised is ignored.
_SECTION_ALIASES = {
    "discussion": "discussion",
    "discussion topics": "discussion",
    "topics": "discussion",
    "agenda": "discussion",
    "decisions": "decisions",
    "decided": "decisions",
    "action items": "tasks",
    "actions": "tasks",
    "action item": "tasks",
    "tasks": "tasks",
    "next steps": "tasks",
    "workgroup changes": "moves",
    "workgroup moves": "moves",
    "assignments": "moves",
    # Context the team wants in the document but not in the graph. Recognised so
    # its prose does not get read as decisions; then ignored.
    "notes": "ignored",
    "context": "ignored",
    "links": "ignored",
    "key links": "ignored",
}


def _split_people(value: str) -> list[str]:
    people = []
    for raw in re.split(r"[,;]| and ", value):
        name = raw.strip().strip("*_`")
        # Drop a trailing "(role)" annotation but keep the name.
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
        if name and name.lower() not in {"none", "n/a", "-"}:
            people.append(name)
    return people


def _parse_task_line(line: str, registry: WorkgroupRegistry) -> ExtractedTask | None:
    checkbox = _CHECKBOX_RE.match(line)
    if checkbox:
        body = line[checkbox.end() :]
        status = "done" if checkbox.group(1).lower() == "x" else "open"
    elif _BULLET_RE.match(line):
        body = _BULLET_RE.sub("", line)
        status = "unknown"
    else:
        return None

    # Everything before the first `key:` marker is the description; the rest is
    # a sequence of key/value segments.
    matches = list(_FIELD_RE.finditer(body))
    description = _TRAILING_SEP.sub("", body[: matches[0].start()] if matches else body).strip()
    if not description:
        return None

    owners: list[str] = []
    workgroup: str | None = None
    due = ""
    explicit_id: str | None = None
    for i, match in enumerate(matches):
        key = (
            match.group(1).lower().rstrip("s")
            if match.group(1).lower().startswith("owner")
            else match.group(1).lower()
        )
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        value = _TRAILING_SEP.sub("", body[match.end() : end]).strip()
        if not value:
            continue
        if key == "owner":
            owners.extend(_split_people(value))
        elif key == "workgroup":
            workgroup = registry.resolve(value)
        elif key == "status":
            candidate = value.strip().lower().replace(" ", "_").replace("-", "_")
            if candidate in TASK_STATUSES:
                status = candidate
        elif key == "due":
            due = value
        elif key in {"id", "key"}:
            explicit_id = value

    return ExtractedTask(
        description=description,
        owners=[ExtractedPerson(name=n) for n in owners],
        workgroup=workgroup,
        status=status,
        due=due,
        explicit_id=explicit_id,
    )


# A line that finishes a sentence finishes the item. Without this, three topics
# on three lines merge into one, and a decision wrapped over two lines splits in
# half. Trailing markup is allowed after the stop.
_ENDS_SENTENCE_RE = re.compile(r"[.!?][\"'\)\]*_]*$")

# Full stops that do not end a sentence. Without these, "e.g." and an initial
# both look like the end of a decision and split it in two. Deliberately a short
# fixed list rather than sentence segmentation: this parser reads a template,
# and guessing at prose is the LLM extractor's job.
_ABBREVIATIONS = frozenset(
    """e.g. i.e. etc. vs. cf. approx. no. nos. fig. viz. al. dr. mr. mrs. ms. prof.
    st. jan. feb. mar. apr. jun. jul. aug. sept. sep. oct. nov. dec.""".split()
)
_TRAILING_TOKEN_RE = re.compile(r"([\w.]+)[\"'\)\]*_]*$")


def _ends_item(line: str) -> bool:
    """Does this line finish the topic or decision being accumulated?"""
    if not _ENDS_SENTENCE_RE.search(line):
        return False
    token = _TRAILING_TOKEN_RE.search(line)
    if not token:
        return True
    word = token.group(1).lower()
    if word in _ABBREVIATIONS:
        return False
    # A single initial, as in "reviewed by A." or a wrapped "J. Smith".
    return not re.fullmatch(r"[a-z]\.", word)

_HEADING_MARKUP_RE = re.compile(r"^\s*(?:#{1,3}\s*)?\*{0,2}\s*")
_HEADING_LABEL_RE = re.compile(r"^(?:meetings?|date)\s*:\s*", re.IGNORECASE)


def _clean_heading(line: str) -> str:
    """Strip whatever markup the export left on a meeting's first line.

    ``## 2026-01-09 — Kickoff`` and ``Meeting: 2026-01-09 | Kickoff`` both reduce
    to the date plus the title.
    """
    text = _HEADING_MARKUP_RE.sub("", line.strip()).strip("*_ ").strip()
    return _HEADING_LABEL_RE.sub("", text).strip()


class _TaskBlock:
    """An action item written as a ``Task:`` block over several lines.

    Absent and blank are the same thing here: neither is permission to guess.
    ``Owner:`` with nothing after it means the meeting did not name an owner, so
    the task comes out unassigned, which is a signal worth seeing.
    """

    def __init__(self, description: str) -> None:
        self.description = description.strip()
        self.has_fields = False
        self.owners: list[str] = []
        self.workgroup: str | None = None
        self.status = "unknown"
        self.due = ""
        self.explicit_id: str | None = None

    def extend_description(self, line: str) -> None:
        self.description = f"{self.description} {line}".strip()

    def set(self, key: str, value: str, registry: WorkgroupRegistry) -> None:
        self.has_fields = True
        key = key.lower()
        value = value.strip()
        if not value:
            return
        if key.startswith("owner"):
            self.owners.extend(_split_people(value))
        elif key == "workgroup":
            self.workgroup = registry.resolve(value)
        elif key == "status":
            candidate = value.lower().replace(" ", "_").replace("-", "_")
            if candidate in TASK_STATUSES:
                self.status = candidate
        elif key == "due":
            self.due = value
        elif key in {"id", "key"}:
            self.explicit_id = value

    def build(self) -> ExtractedTask | None:
        if not self.description:
            return None
        return ExtractedTask(
            description=self.description,
            owners=[ExtractedPerson(name=name) for name in self.owners],
            workgroup=self.workgroup,
            status=self.status,
            due=self.due,
            explicit_id=self.explicit_id,
        )


def _parse_decision_line(line: str, registry: WorkgroupRegistry) -> ExtractedDecision | None:
    if not _BULLET_RE.match(line):
        return None
    body = _BULLET_RE.sub("", line).strip()
    workgroup = None
    prefix = _PARENTHETICAL_WG_RE.match(body)
    if prefix:
        resolved = registry.resolve(prefix.group(1))
        if resolved:
            workgroup = resolved
            body = body[prefix.end() :].strip()
    if not body:
        return None
    return ExtractedDecision(statement=body, workgroup=workgroup)


def extract_meeting_markdown(
    section_text: str, registry: WorkgroupRegistry
) -> ExtractedMeeting | None:
    """Parse one meeting section. Returns ``None`` when the section has no date.

    A section without a date is not a meeting. It is the document's preamble, a
    links list, or a heading, so we skip it rather than inventing a date.
    """
    lines = section_text.splitlines()
    if not lines:
        return None

    heading = _clean_heading(lines[0])
    date_match = _ISO_DATE_RE.search(heading)
    if not date_match:
        # Fall back to an explicit `Date:` line inside the section.
        for line in lines[1:]:
            if line.lower().startswith("date:"):
                date_match = _ISO_DATE_RE.search(line)
                break
    if not date_match:
        return None
    date = datetime.date.fromisoformat(date_match.group(1))

    title = heading.replace(date_match.group(1), "", 1)
    title = _TRAILING_SEP.sub("", _LEADING_SEP.sub("", title)).strip()
    title = title or heading

    organizer: ExtractedPerson | None = None
    attendees: list[str] = []
    declared_workgroups: list[str] = []
    topics: list[str] = []
    decisions: list[ExtractedDecision] = []
    tasks: list[ExtractedTask] = []
    moves: list[ExtractedWorkgroupMove] = []

    section = "header"
    open_task: _TaskBlock | None = None
    paragraph: list[str] = []

    def flush_task() -> None:
        nonlocal open_task
        if open_task is not None:
            built = open_task.build()
            if built is not None:
                tasks.append(built)
            open_task = None

    def flush_paragraph() -> None:
        """Close the topic or decision being accumulated.

        Called on a blank line, a heading, and whenever a line ends a sentence.
        The sentence rule is what lets topics sit one per line while a decision
        wraps across two, without the template having to say which is which.
        """
        if not paragraph:
            return
        text = " ".join(paragraph).strip()
        paragraph.clear()
        if not text:
            return
        if section == "discussion":
            topics.append(text)
        elif section == "decisions":
            decision = _parse_decision_line("- " + text, registry)
            if decision:
                decisions.append(decision)

    for line in lines[1:]:
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_task()
            continue

        # A section heading, written either as `###` or as a bare line.
        sub = _SUBHEADING_RE.match(line)
        bare = None if sub else _BARE_HEADING_RE.match(line)
        heading_text = None
        if sub:
            heading_text = sub.group(1)
        elif bare and _SECTION_ALIASES.get(bare.group(1).strip().lower()):
            heading_text = bare.group(1)
        if heading_text is not None:
            flush_paragraph()
            flush_task()
            section = _SECTION_ALIASES.get(heading_text.strip().lower(), "other")
            continue

        label = _LABEL_RE.match(line)
        if label:
            flush_paragraph()
            flush_task()
            key, value = label.group(1).lower(), label.group(2)
            if key in {"facilitator", "organizer", "organiser"}:
                names = _split_people(value)
                if names:
                    organizer = ExtractedPerson(name=names[0])
            elif key in {"attendees", "present"}:
                attendees.extend(_split_people(value))
            elif key == "workgroups":
                for raw in re.split(r"[,;]", value):
                    slug = registry.resolve(raw)
                    if slug and slug not in declared_workgroups:
                        declared_workgroups.append(slug)
            continue

        if section == "ignored":
            continue

        if section == "tasks":
            opened = _TASK_OPEN_RE.match(line)
            if opened:
                flush_task()
                open_task = _TaskBlock(opened.group(1))
                continue
            if open_task is not None:
                field = _TASK_FIELD_RE.match(line)
                if field:
                    open_task.set(field.group(1), field.group(2), registry)
                elif not open_task.has_fields:
                    # A long description wrapped onto the next line. Only before
                    # the first field, so a stray line after `Due:` cannot be
                    # appended to the description.
                    open_task.extend_description(stripped)
                continue
            # The one-line bullet form, still supported.
            task = _parse_task_line(line, registry)
            if task:
                tasks.append(task)
            continue

        if section == "discussion":
            if _BULLET_RE.match(line):
                flush_paragraph()
                topic = _BULLET_RE.sub("", line).strip()
                if topic:
                    topics.append(topic)
            else:
                paragraph.append(stripped)
                if _ends_item(stripped):
                    flush_paragraph()
        elif section == "decisions":
            if _BULLET_RE.match(line):
                flush_paragraph()
                decision = _parse_decision_line(line, registry)
                if decision:
                    decisions.append(decision)
            else:
                paragraph.append(stripped)
                if _ends_item(stripped):
                    flush_paragraph()
        elif section == "moves" and _BULLET_RE.match(line):
            match = _JOINS_RE.match(_BULLET_RE.sub("", line).strip())
            if match:
                slug = registry.resolve(match.group("wg"))
                if slug:
                    moves.append(
                        ExtractedWorkgroupMove(
                            person=ExtractedPerson(name=match.group("person").strip()),
                            workgroup=slug,
                        )
                    )
        elif section == "moves":
            match = _JOINS_RE.match(stripped)
            if match:
                slug = registry.resolve(match.group("wg"))
                if slug:
                    moves.append(
                        ExtractedWorkgroupMove(
                            person=ExtractedPerson(name=match.group("person").strip()),
                            workgroup=slug,
                        )
                    )

    flush_paragraph()
    flush_task()

    # Workgroups discussed = the ones declared on the header line, plus any that
    # the meeting's own tasks and decisions actually touch.
    workgroups = list(declared_workgroups)
    for slug in (
        [t.workgroup for t in tasks]
        + [d.workgroup for d in decisions]
        + [m.workgroup for m in moves]
    ):
        if slug and slug not in workgroups:
            workgroups.append(slug)

    # The organizer is not repeated in the attendee list.
    if organizer:
        attendees = [a for a in attendees if a != organizer.name]

    summary = "; ".join(topics[:3])

    return ExtractedMeeting(
        date=date,
        title=title,
        summary=summary,
        organizer=organizer,
        attendees=[ExtractedPerson(name=n) for n in dict.fromkeys(attendees)],
        topics=topics,
        workgroups=workgroups,
        decisions=decisions,
        tasks=tasks,
        workgroup_moves=moves,
    )


# ---------------------------------------------------------------------------
# LLM extractor
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """\
You read conference-organizing meeting notes and extract structured information.

Given one meeting section in Markdown, extract:
- the meeting date (required, ISO format; look in the heading first);
- a short title and summary;
- the facilitator or organizer, ONLY if the notes name one;
- attendees, excluding the organizer;
- discussion topics;
- decisions the meeting actually recorded;
- action items, with their owners, workgroup, status and deadline;
- people the notes record as joining a workgroup.

Rules you must not break:
- Extract only what the text states. Do not infer an owner, a status, a
  decision or a deadline that the notes do not support.
- If an action item has no named owner, return an empty owner list. An
  unassigned task is a useful signal; a guessed owner is a bug.
- status must be one of: unknown, open, in_progress, blocked, done, dropped.
  Use "unknown" unless the notes state or clearly mark it.
- workgroup must be one of the slugs below, or null. Never invent a slug.
- explicit_id must be copied from an "id:" written in the notes, or null. Never
  invent one; the pipeline derives its own key when there is none.

Workgroups:
{workgroups}
"""


async def extract_meeting_llm(
    section_text: str, registry: WorkgroupRegistry, model: str
) -> ExtractedMeeting | None:
    """Extract via instructor + LiteLLM. Imports are local so the deterministic
    path never pulls in the LLM stack."""
    import instructor
    import litellm

    litellm.drop_params = True
    client = cast(
        "instructor.AsyncInstructor",
        instructor.from_litellm(litellm.acompletion, mode=instructor.Mode.JSON),
    )
    result = await client.chat.completions.create(
        model=model,
        response_model=ExtractedMeeting,
        messages=[
            {
                "role": "system",
                "content": EXTRACT_PROMPT.format(workgroups=registry.prompt_listing()),
            },
            {"role": "user", "content": section_text},
        ],
    )
    # Re-validate to restore class identity for pickling by CocoIndex's memo cache.
    meeting = ExtractedMeeting.model_validate(result.model_dump())
    return _sanitize(meeting, registry)


def _sanitize(meeting: ExtractedMeeting, registry: WorkgroupRegistry) -> ExtractedMeeting:
    """Drop anything the model returned that isn't in the registry or the status
    vocabulary. The graph should never contain a slug or status we didn't define."""
    meeting.workgroups = [s for s in dict.fromkeys(meeting.workgroups) if registry.get(s)]
    for task in meeting.tasks:
        if task.workgroup and not registry.get(task.workgroup):
            task.workgroup = registry.resolve(task.workgroup)
        if task.status not in TASK_STATUSES:
            task.status = "unknown"
    for decision in meeting.decisions:
        if decision.workgroup and not registry.get(decision.workgroup):
            decision.workgroup = registry.resolve(decision.workgroup)
    meeting.workgroup_moves = [
        m
        for m in meeting.workgroup_moves
        if registry.get(m.workgroup) or registry.resolve(m.workgroup)
    ]
    for move in meeting.workgroup_moves:
        move.workgroup = (
            move.workgroup
            if registry.get(move.workgroup)
            else cast(str, registry.resolve(move.workgroup))
        )
    return meeting
