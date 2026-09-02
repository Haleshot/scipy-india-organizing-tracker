# Writing meeting notes

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

Facilitator: Srihari Thyagarajan
Attendees: Srihari Thyagarajan, Agriya Khetarpal, Malayaja Chutani
Workgroups: Registration & Help Desk, Website, Program Committee

Topics

Volunteer applications received since the last call.
Who should handle the first round of intro calls.
Website work needed before the next public announcement.

Decisions

(Registration & Help Desk) We schedule a short intro call before assigning any
new applicant to a role, rather than placing people from a form answer.

(Website) The 2026 site reuses the existing structure rather than starting from
a blank project.

Action items

Task: Schedule intro calls with the shortlisted volunteers
ID: intro-calls
Workgroup: Registration & Help Desk
Owner: Srihari Thyagarajan
Status: open
Due: 2026-09-10

Task: Stand up our own pretalx instance for talk submissions
ID: pretalx-instance
Workgroup: Website
Owner: Agriya Khetarpal
Issue: #41
Status: in_progress
Due: 2026-09-12

Task: Recruit additional CFP reviewers
ID: cfp-reviewer-recruitment
Workgroup: Program Committee
Owner:
Status: open
Due:

Workgroup changes

Malayaja Chutani joins Program Committee

Notes

There is more interest in Program Committee than there is review work for right
now. Revisit assignments after the next CFP planning call.
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
"Website", "website-tech" and "web" all land on the same workgroup. A
name that matches nothing is dropped rather than invented, so an unregistered
work area shows up as a gap rather than a wrong edge.

`Topics` and `Decisions` take ordinary paragraphs. A blank line separates one
from the next, and a topic that is one line per item works too, as do bullets if
you prefer them.

A decision can name the workgroup it concerns by opening with it in brackets:

```text
Decisions

(Website) The 2026 website will reuse the existing site structure.

The organizing team meets every second Friday until the conference.
```

That prefix is what "what did we decide about the website" reads. Leave it off
when a decision belongs to the whole team, as the second one here does.

`Action items` is the part with structure. Each item opens with `Task:` and the
lines after it belong to that item until the next `Task:` or a blank line.

`Workgroup changes` records somebody taking on a volunteer role, written as
"Name joins Role". That is what puts a person on a role in the graph, and it is
deliberately something a human states rather than something inferred from who
happened to own a task in that area.

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

## Linking a task to a GitHub issue

`Issue:` on an action item joins it to an issue in the tracker:

```text
Task: Apply to the FOSS United Events grant
ID: foss-united-grant
Workgroup: Sponsoring
Owner: Agriya Khetarpal
Issue: #44
Status: open
```

The dashboard then shows the task's status from the notes beside the issue's
state on GitHub, which is how the two get compared. `#44` means the first
repository in `GITHUB_REPOS`; write `owner/repo#44` for any other. Several
issues on one line is fine.

This link is only ever made because a note said so. The pipeline will not decide
that a task and an issue are the same work because their wording is close. See
[Connecting the sources](connecting-sources.md).

## IDs and repeated tasks

An action item repeated in a later meeting is the same action item, and that is
how its status moves from `open` to `in_progress` to `done` over several weeks.
The pipeline works out identity from the workgroup and the wording when you give
it nothing else, which is fine for most items.

`ID:` is worth adding in two cases. The first is an item likely to be reworded:
without an ID, "Stand up pretalx" and "Stand up our own pretalx instance" are
two different tasks. The second is two items in one workgroup that genuinely read
the same, where the ID is the only thing that keeps them apart.

To carry a task forward, repeat it with the same ID and the new status:

```text
Action items

Task: Stand up our own pretalx instance for talk submissions
ID: pretalx-instance
Workgroup: Website
Owner: Agriya Khetarpal
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
