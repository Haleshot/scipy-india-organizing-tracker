# Reading the dashboard

The dashboard is one page per question. Nothing on it is typed by hand: every
number comes from the meeting notes or the planning tracker, and it is only as
current as the last time somebody ran a refresh. The footer says when that was.

## Overview

Opens with the number that usually matters, how many action items are still
open and how many of those have nobody on them.

Unowned work is called out separately because it is the failure mode that hides.
An item with an owner and no progress gets chased at the next meeting. An item
nobody picked up sits in the notes looking like it is handled. The pipeline
never assigns an owner, so when this says four, four action items were written
down without a name against them.

Below that is the most recent meeting with its decisions, then a table of open
work per volunteer role, then the unowned items in full.

## Action items

Everything the meetings agreed to do. Statuses are `open`, `in progress`,
`blocked`, `done`, `dropped`, and `unknown`.

`unknown` means the notes never said, and it counts as open. If a meeting stops
mentioning an item, that is not evidence the item finished.

An action item repeated across meetings is one row, not several. Its status is
whatever the most recent meeting said, and the whole history sits behind it, so
you can see something go open, blocked, in progress over six weeks.

## Meetings

One entry per dated meeting: who was there, what was decided, and which action
items were touched. Items that changed status are marked, which is the fastest
way to answer what actually moved since last time.

## GitHub issues

The planning tracker, read straight from GitHub. This is a second source and it
disagrees with the notes on purpose.

An issue is linked to an action item only when somebody wrote that link into the
notes. Nothing here guesses that two similarly worded things are the same work.
So the "Linked to an action item" filter is small, and the gap between the two
lists is the interesting part: work the room agreed to that nobody filed, and
issues sitting in the tracker that no meeting has discussed.

## Volunteer roles

The thirteen roles from the sign-up form, each with its open work and who is on
it. A role with nobody on it shows as empty rather than being hidden, because an
empty role is worth seeing.

Nobody who filled in the volunteer form is named here. See
[what gets published](privacy.md).

## People

Everyone who appears in the notes: what they own, which roles they hold, which
meetings they attended. Three people today, the ones listed at
[scipy.in/2026/team](https://scipy.in/2026/team).

## Explorer

All of the above is one graph, and this draws it. People, roles, meetings,
decisions, action items and issues are nodes; the lines between them are things
like "attended", "owns", "decided", "belongs to".

Search for a person or a role and pick it, and you get that one thing with what
it connects to. **Directly connected** shows one step out. **One step further
out** also brings in the neighbours of those, which is how you find who you
share work with without having been in the same meeting. Click any node to read
it in the panel.

Meetings, action items and issues start hidden under **Display**, because
turning them all on at once produces a hairball nobody can read. Add them once
you have narrowed to something small.

## What is not on it

Contact details, volunteer form answers, the names of people who applied to
volunteer and have not been assigned, and file paths into anyone's Drive. The
exporter works from an allowlist, so a field added to the graph later does not
appear here unless somebody adds it to that list on purpose.

[What gets published](privacy.md) has the detail.
