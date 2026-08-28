# The meeting-notes template

This is the shape the deterministic extractor reads. It is meant to be typed
during a call by a person, not filled in afterwards like a form, so it is built
out of plain labels rather than tables, checkboxes or anything else that depends
on markup surviving a copy and paste.

That matters more than it sounds. The same Google Doc reaches the pipeline as
two different things: if you download it as Markdown you get `##` headings and
`-` bullets, and if CocoIndex reads it through the Google Drive connector you
get plain text with neither. Labels like `Meeting:` and `Task:` are still there
in both, which is why the format is built on them.

Write normally inside the sections. The labels give the parser something
reliable to hold on to; the prose between them is yours.

## The template

```text
SciPy India 2026 meeting notes

Meeting: 2026-09-05 | Volunteer onboarding

Facilitator: Priya Vasudevan
Attendees: Priya Vasudevan, Meera Raghavan, Kabir Anand, Sanjana Iyer
Workgroups: Volunteers, Website & Tech, Program & CFP

Topics

Volunteer applications received since the last call.
Who should handle the first round of intro calls.
Website work needed before the next public announcement.

Decisions

(Volunteers) The Volunteers workgroup will schedule a short intro call before
assigning new applicants to a workgroup.

The 2026 website will reuse the existing site structure rather than start
from a blank project.

Action items

Task: Schedule intro calls with the shortlisted volunteers
ID: volunteer-intro-calls
Workgroup: Volunteers
Owner: Priya Vasudevan
Status: open
Due: 2026-09-10

Task: Port the existing site structure and publish a holding page
ID: website-holding-page
Workgroup: Website & Tech
Owner: Kabir Anand
Status: in_progress
Due: 2026-09-12

Task: Recruit additional CFP reviewers
ID: cfp-reviewer-recruitment
Workgroup: Program & CFP
Owner:
Status: open
Due:

Notes

We have more interest in Program & CFP than we currently have review work
for. Revisit assignments after the next CFP planning call.
```

## What each part does

`Meeting:` opens a new meeting and is the only line the parser insists on. The
date has to be ISO, `YYYY-MM-DD`, because a date written as "5 Sep" is ambiguous
enough that guessing it wrong is worse than skipping the section. Anything after
the `|` becomes the title. A section with no date is treated as preamble and
dropped, which is how the document header and a links list stay out of the
graph.

`Facilitator:`, `Attendees:` and `Workgroups:` are comma-separated. Workgroup
names are matched against `config/workgroups.yaml`, including its aliases, so
"Website & Tech", "website-tech" and "web" all land on the same workgroup. A
name that matches nothing is dropped rather than invented, so an unregistered
work area shows up as a gap rather than a wrong edge.

`Topics` and `Decisions` take ordinary paragraphs. A blank line separates one
from the next, and a topic that is one line per item works too, as do bullets if
you prefer them.

A decision can name the workgroup it concerns by opening with it in brackets:

```text
Decisions

(Website & Tech) The 2026 website will reuse the existing site structure.

The organizing team meets every second Friday until the conference.
```

That prefix is what "what did we decide about the website" reads. Leave it off
when a decision belongs to the whole team, as the second one here does.

`Action items` is the part with structure. Each item opens with `Task:` and the
lines after it belong to that item until the next `Task:` or a blank line.

`Notes` is for context you want in the document that is not a decision or an
action item. The parser recognises the heading so the prose underneath does not
get read as a decision, then ignores it. Nothing from `Notes` reaches the graph.

## Blank fields mean "we did not decide"

An empty `Owner:` is not the same as a missing one, and neither is permission to
guess. Both come out as an unassigned task, and the dashboard and the
`list_unassigned_tasks` tool are built around exactly that signal. The same goes
for `Due:` and `Status:`: a task with no recorded status is `unknown`, and
`unknown` is treated as still open, because the notes not saying an item is
finished is not evidence that it is.

Recognised statuses are `open`, `in_progress`, `blocked`, `done`, `dropped` and
`unknown`. Anything else falls back to `unknown`.

## IDs and repeated tasks

An action item repeated in a later meeting is the same action item, and that is
how its status moves from `open` to `in_progress` to `done` over several weeks.
The pipeline works out identity from the workgroup and the wording when you give
it nothing else, which is fine for most items.

`ID:` is worth adding in two cases. The first is an item likely to be reworded:
without an ID, "Port the site" and "Port the existing site structure" are two
different tasks. The second is two items in one workgroup that genuinely read
the same, where the ID is the only thing that keeps them apart.

To carry a task forward, repeat it with the same ID and the new status:

```text
Action items

Task: Port the existing site structure and publish a holding page
ID: website-holding-page
Workgroup: Website & Tech
Owner: Kabir Anand
Status: done
Due: 2026-09-12
```

The graph keeps one task with a three-meeting history rather than three tasks.

## Things that do not break it

The parser is meant to survive normal human notes, so an extra paragraph under
`Notes`, a missing `Topics` section, a meeting with no action items, `Owner`
written before `Workgroup`, and a stray `**bold**` left over from an export are
all fine. `tests/test_note_formats.py` covers each of those.

What does break it is a missing or non-ISO date on the `Meeting:` line, since
that is the one thing the parser will not guess.

## When to use the LLM extractor instead

If minutes get taken as free prose and nobody is going to type `Owner:` during a
call, set `MEETING_EXTRACTOR=llm`. It reads the same Pydantic schema and is
under the same instruction not to infer anything the text does not support, but
it is a language model, so check it with `scripts/eval_extraction.py` before
trusting a graph built that way. The two extractors can read the same document;
they do not have to agree, and the eval harness exists to show you where they
do not.
