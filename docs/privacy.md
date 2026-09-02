# Privacy boundary

GitHub Pages is static and public, so the browser never talks to Neo4j and never
talks to the MCP server. The published file is produced by
[scripts/export_public_snapshot.py](../scripts/export_public_snapshot.py), which
works from an allowlist: `PUBLIC_FIELDS` names every field that may be published,
per node label. Anything not named there cannot leak, including fields added to
the graph later.

There are two profiles. `public` is the default and the only one the Pages
workflow will deploy: nothing that originated in a volunteer application reaches
it, so no availability, no skills, no interests, and no names of people who
applied but have not been assigned. A person appears in it through work they did
in the open, and the site shows waiting volunteers as counts per workgroup.

```bash
python scripts/export_public_snapshot.py                       # public, committed
python scripts/export_public_snapshot.py --profile organizer   # private/, gitignored
```

`organizer` adds availability, skills and interests for people already on a
workgroup, which is useful when you are deciding who to ask about what. It
writes to `private/organizer-graph.json`, outside `web/` so it cannot be
deployed by accident, and the Pages workflow rejects any snapshot whose profile
is not `public`.

Also excluded from both: contact details, raw application answers, and
`note_file` paths into somebody's Drive. `--include-applicant-names` publishes
the waiting list by name, and you should only pass it if the form told
applicants their names would be public.

Fixture data makes the difference between the profiles look harmless. Real
applications are the reason the default is the strict one.

## Issues are already public

GitHub issue titles, states, labels and assignees are published as they are,
because they are already published: anyone can read
[scipy-india/planning](https://github.com/scipy-india/planning/issues). Issue
bodies are the exception and are never read at all, because a comment thread is
where somebody eventually pastes an email address or a phone number.

## Credentials

The Google service-account key is the one file in this project that is genuinely
dangerous to leak. It belongs in `secrets/`, which `.gitignore` covers along
with every JSON file at the repository root, because the name Google gives the
download is `<project>-<hash>.json` and no generic pattern catches that.

`test_no_tracked_file_contains_a_private_key` scans every tracked file for the
markers a key contains and fails the build if it finds one. That checks the
outcome rather than the pattern, which is the only version of this check worth
having.

Folder ids, project ids and repository names are not secrets. See
[Connecting the sources](connecting-sources.md).

[tests/test_public_snapshot.py](../tests/test_public_snapshot.py) enforces this
against the committed snapshot, and `./scripts/refresh.sh` runs those tests on
the file it just wrote.
