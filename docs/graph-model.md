# The graph model

What the labels and relationships mean, and the reasoning behind task identity,
the decision edges and the provenance fields. Read this before writing Cypher
against the graph, or before deciding a query gave you a surprising answer.

Seven node labels and thirteen relationship types, plus a singleton that records
how the graph was built.

```mermaid
graph LR
    P[Person] -->|ATTENDED| M[Meeting]
    M -->|DECIDED| D[Decision]
    D -->|CONCERNS| W[Workgroup]
    M -->|CREATED_ACTION| T[Task]
    M -->|TOUCHED_ACTION| T
    P -->|ASSIGNED_TO| T
    T -->|BELONGS_TO| W
    M -->|DISCUSSED| W
    P -->|MEMBER_OF| W
    P -->|INTERESTED_IN| W
    P -->|SUBMITTED| A[VolunteerApplication]
    T -->|TRACKED_BY| I[Issue]
    P -->|WORKS_ON| I
    I -->|FILED_UNDER| W
```

| Node | Key | Properties |
| --- | --- | --- |
| `Meeting` | `id` | `note_file`, `date`, `title`, `summary`, `topics`, `section_index`, `source_ref`, `extraction_mode` |
| `Person` | `name` | canonical name after entity resolution |
| `Task` | `id` | `description`, `status`, `due`, `note_file`, `identity_basis`, `first_seen`, `last_seen`, `meeting_count`, `extraction_mode` |
| `Workgroup` | `slug` | `name`, `description` |
| `Decision` | `statement` | `note_file`, `first_seen`, `extraction_mode` |
| `Issue` | `key` | `repo`, `number`, `title`, `url`, `state`, `state_reason`, `labels`, `assignee_logins`, `milestone`, `comment_count`, `created_at`, `updated_at` |
| `VolunteerApplication` | `application_id` | `display_name`, `status`, `availability`, `interests`, `skills`, `submitted_on`, and the private `contact_email`, `contact_phone`, `raw_response` |
| `GraphBuild` | `id` | `built_at`, `pipeline_version`, `notes_source`, `volunteer_source`, `extraction_mode`, `person_resolution`, `issue_source`, `issue_count` |

Workgroups come from [config/workgroups.yaml](../config/workgroups.yaml) and
nowhere else. That file also holds the aliases that let "Design", "design &
branding" and "Creatives" all land on one workgroup. A name that matches nothing
is dropped rather than invented, so an unregistered work area shows up as a gap
instead of a wrong edge.

People come from `config/people.yaml`, which also maps GitHub logins to names.
That mapping is written down rather than derived, because nothing about the
string `malayajac` reveals that it means Malayaja Chutani, and an entity
resolver confident enough to guess that would also be confident enough to merge
two different people.

### Two sources, joined only where somebody said so

`Task` comes from the meeting notes; `Issue` comes from GitHub. They describe
overlapping work and the pipeline will not decide which pairs match. The only
thing that creates `TRACKED_BY` is an `Issue:` line on an action item, written
by whoever took the minutes.

Fuzzy title matching would produce an edge that is right most of the time, which
means checking every edge before trusting any of them. `WORKS_ON` and
`FILED_UNDER` follow the same rule: an assignee
becomes an edge only when `config/people.yaml` names them, and a label becomes a
workgroup only when `config/workgroups.yaml` lists it.

### Decisions and action items are different things

The upstream example has no `Decision` node, so it spends `DECIDED` on the
meeting-to-task edge: there, a task *is* the thing that got decided. Once
decisions became their own nodes here that name stopped being true, so `DECIDED`
now points at the decision and action items get two edges of their own.
`CREATED_ACTION` marks the one meeting that first recorded an item.
`TOUCHED_ACTION` marks every meeting that mentioned it, carrying the status it
held at that point.

"Which meeting created this" and "how many meetings has this dragged through"
are now separate questions with separate answers, and the whole `open → blocked
→ in_progress` history lives in the graph rather than only in the prose. If you
know the upstream example, read `CREATED_ACTION` where you expect `DECIDED`.

### Task identity

Upstream keys a task by its description, and this project leaned on that: an
item repeated in a later meeting is the same item, which is how status moves
along. That recurrence is worth keeping. Description-only identity is not. Two
workgroups will eventually both write "Send the reminder email", and a
description-keyed graph merges them into one task with one status and two
unrelated owners without anything looking broken.

[src/scipy_india_kg/task_identity.py](../src/scipy_india_kg/task_identity.py)
resolves a scoped key instead: an explicit `ID:` from the notes if there is one,
otherwise the workgroup plus the normalised description, otherwise the
description alone. Every key is also scoped to the source document so last
year's notes and this year's never merge. Normalisation folds case, whitespace
and trailing punctuation and nothing cleverer, because near-duplicate wording
staying two tasks is the safe direction to be wrong in. Which rule fired is
stored on the node as `identity_basis`.

### Provenance

Before trusting anything an LLM extracted you want to be able to ask why the
graph believes it, so every derived fact carries its source. `Meeting.source_ref`
points at `<note file>#section-<n>`. Meetings, tasks and decisions all record
which extractor produced them. `TOUCHED_ACTION` edges give a task's whole
appearance history with the status at each point, `ASSIGNED_TO.first_meeting_id`
credits the meeting that first named an owner, and `MEMBER_OF.source`
distinguishes a membership the team recorded in a meeting from one inferred from
a form field.

`./scripts/query get-task-history "sponsorship deck"` prints all of it. Raw
source text is deliberately not copied into the graph, and none of this
provenance reaches the public snapshot beyond the build-mode names in the
dashboard footer.
