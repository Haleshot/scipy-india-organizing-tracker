# Adding to it

Everything on the dashboard came from one of two places, and both are things you
already do. Nothing here needs the pipeline running on your machine.

## What is in there so far

Five meetings from July and August 2026, covering the kickoff, the sponsorship
deck, the budget, the IIT Madras visit and the first volunteer call. Around
twenty action items across thirteen volunteer roles, plus whatever
[scipy-india/planning](https://github.com/scipy-india/planning/issues) holds.

That is a start, not a record. It grows the same way it got here.

## Adding work

=== "In the meeting notes"

    Type it into the Doc during the call, under `Action items`:

    ```text
    Task: Book the tutorial rooms with IIT Madras estates
    ID: tutorial-rooms
    Workgroup: Logistics
    Owner: Malayaja Chutani
    Status: open
    Due: 2026-09-20
    ```

    `Task:` and a description are the only lines that have to be there. Leave
    `Owner:` blank when nobody took it, and it shows up on the dashboard's
    unowned list, which is exactly where it should be.

    Bring the same item up at the next meeting with the same `ID:` and a new
    `Status:`, and it stays one item with a history rather than becoming two.

    The full format is [Writing meeting notes](writing-notes.md).

=== "As a GitHub issue"

    Open one on
    [scipy-india/planning](https://github.com/scipy-india/planning/issues) the
    way you already would. It appears on the dashboard's issues page at the next
    refresh.

    Two things make it more useful:

    **Assign somebody.** The assignee becomes a person in the graph if their
    GitHub login is in `config/people.yaml`, so their work shows up in one place
    rather than two.

    **Label it with a volunteer role.** A label matching a role in
    `config/workgroups.yaml`, like `logistics` or `sponsoring`, files the issue
    under that role. Any other label is ignored rather than guessed at.

## Joining the two

An action item and an issue about the same work stay unconnected unless a note
says otherwise. Add an `Issue:` line:

```text
Task: Apply to the FOSS United Events grant
ID: foss-united-grant
Workgroup: Sponsoring
Owner: Agriya Khetarpal
Issue: #44
Status: open
```

The dashboard then shows both statuses on one line, so you can see an item the
notes call open sitting against an issue GitHub closed last week.

Nothing infers this link. Two things with similar titles are not evidence they
are the same work, and an edge that is right most of the time means checking all
of them.

## Adding a person

`config/people.yaml`, which is three entries long:

```yaml title="config/people.yaml"
people:
  - name: Malayaja Chutani
    github: malayajac
    aliases: [Malayaja]
```

`aliases` are the other spellings that should resolve to this person. `github`
is what connects an issue assignee to a name, since nothing about a login says
whose it is.

Somebody can turn up in the notes without being in this file. They still get a
node; they just do not get their GitHub issues attached.

## Adding a volunteer role

`config/workgroups.yaml`. The thirteen there came from the sign-up form. A role
with nobody on it still shows on the dashboard, because an empty role is worth
seeing.

## Then what

Somebody with the pipeline set up runs `./scripts/refresh.sh` and the dashboard
updates. That is deliberately a person rather than a schedule, so changes get
looked at before they go out. [Keeping it current](refreshing.md) covers doing
it on a timer if you would rather.
