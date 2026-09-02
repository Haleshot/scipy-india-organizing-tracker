# Reading the dashboard

[Open the dashboard](../){ .md-button .md-button--primary target=_blank } and read this beside it.

Nothing on the dashboard is typed by hand. Every number comes from the meeting
notes or the planning repo, and it is as current as the last refresh, which the
footer gives you a timestamp for.

Six pages, one per question you might have arrived with.

=== "Overview"

    Opens with the count that usually matters: how many action items are still
    open, and how many of those have nobody against them.

    Unowned work gets its own number because it is the thing that goes missing.
    An item with an owner and no progress gets chased next meeting. An item
    nobody took sits in the notes looking handled. Since the pipeline never
    fills in an owner, a four here means four items were written down without a
    name on them.

    Under that: the most recent meeting and what it decided, open work broken
    down by volunteer role, then the unowned items listed out.

=== "Action items"

    Everything the meetings agreed to do, with a status of open, in progress,
    blocked, done, dropped or unknown.

    Unknown means the notes never said, and it counts as open. A meeting going
    quiet about something is not the same as that thing finishing.

    An item that comes up in several meetings is one row here, not several. The
    status shown is whatever the latest meeting said, and the history sits
    behind it, so you can watch something go open, then blocked, then in
    progress across six weeks.

=== "Meetings"

    One entry per dated meeting: who was there, what got decided, and which
    action items came up. Items that changed status are marked, which is the
    quickest way to see what actually moved.

=== "GitHub issues"

    The planning repo, read straight from GitHub.

    An issue is tied to an action item only when somebody wrote that link into
    the notes. Nothing guesses that two similarly worded things are the same
    work, so the linked list stays short on purpose. The gap between the two
    lists is where the useful information is: work the room agreed to that
    nobody filed, and issues sitting in the tracker that no meeting has touched.

=== "Volunteer roles"

    The thirteen roles from the sign-up form, each with its open work and who
    is on it. A role with nobody on it shows as empty rather than being hidden,
    since that is worth knowing.

    Nobody who filled in the volunteer form is named on this page.

=== "People"

    Everyone who turns up in the notes, with what they own, which roles they
    hold and which meetings they were in. Three of us at the moment, the ones
    on [scipy.in/2026/team](https://scipy.in/2026/team).

## The explorer

All of the above is one graph, and the explorer draws it. People, roles,
meetings, decisions, action items and issues are the dots; the lines between
them are things like attended, owns, decided, belongs to.

Search for a person or a role and pick it, and you get that one thing plus what
it connects to.

| Control | What it does |
| --- | --- |
| Directly connected | One step out from whatever you picked |
| One step further out | Also pulls in the neighbours of those, which is how you spot who you share work with without having sat in the same meeting |
| Show everything | Drops the focus and draws the lot |
| Display | Brings in meetings, action items and issues, which start hidden |

Meetings, action items and issues start hidden because turning everything on at
once gives you a hairball. Narrow to something small first, then add them.

!!! tip "The panel does the explaining"

    Clicking a dot opens it in the panel beside the drawing: a person's open
    work, an issue's state on GitHub, a task's whole history. The drawing is for
    finding things, and the panel is for reading them.

## What is not on it

Contact details, volunteer form answers, and file paths into anyone's Drive. The
export works from a list of allowed fields rather than a list of blocked ones,
so a field added to the database later does not turn up here unless somebody
adds it to that list deliberately.

[What gets published](privacy.md) has the detail.
