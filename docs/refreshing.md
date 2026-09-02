# Keeping it current

One command rebuilds everything that comes from the sources:

```bash
./scripts/refresh.sh
```

Three stages, in this order because each needs the one before it. The graph gets
built from the notes and the tracker, the search indexes get built from the
graph, and the dashboard's data file gets exported from the graph and checked
before it is written.

Everything is incremental. A meeting section whose text has not changed is
matched against its cached extraction and skipped, so a refresh after one edited
meeting costs about the same as a refresh after none.

```title="a run after one edited meeting"
1/3  Graph
  ✅ process_note_file: 1 total | 1 reprocessed
  Issue: 43 -> 43
  Task: 22 -> 23

2/3  Search indexes
  vector    task_embedding_index    1 embedded, 22 already current, 384 dims

3/3  Dashboard snapshot
  Wrote web/public/data/graph.json: 5 meetings, 3 people, 23 tasks
  privacy checks passed

Done
  Graph written to: bolt://127.0.0.1:7687 (database neo4j)
```

That last line matters more than it looks. See
[which database am I looking at](neo4j-desktop.md#which-database-am-i-looking-at).

## Flags

| Flag | When you want it |
| --- | --- |
| `--check` | Report what is stale, write nothing. Good in CI, or when you are not sure somebody else already ran it |
| `--reset` | Empty the graph and rebuild. After changing something structural, like a workgroup slug, where incremental updates leave the old version behind |
| `--watch` | Re-run whenever the notes change. Needs `fswatch` |
| `--no-search` | Skip the indexes |
| `--force` | Re-embed everything |

## Doing it on a schedule

Nothing here runs itself. A refresh happens when somebody runs the command, and
for a team this size that is usually the right amount of automation: you get to
see what changed before it goes out.

If you would rather it ran on its own, the honest options are a cron entry on a
machine that stays up, or GitHub Actions. Actions needs a Neo4j the runner can
reach, which a container on your laptop is not, so it wants a hosted instance
such as Aura before it does anything useful.

??? example "A cron entry, if you want one"

    ```bash title="crontab -e"
    # Every weekday at 9am. Absolute paths, because cron has almost no PATH.
    0 9 * * 1-5 cd /path/to/scipy-india-organizing-tracker && ./scripts/refresh.sh >> refresh.log 2>&1
    ```

    Two things to know. The GitHub source allows 60 unauthenticated requests an
    hour, so set `GITHUB_TOKEN` before running this often. And a scheduled
    refresh that fails is silent unless you read the log, which is the usual
    reason people go back to running it by hand.

## Putting the dashboard online

`web/public` is the deployable directory as it stands. No build step, Cytoscape
is vendored rather than pulled from a CDN, every URL is relative and routing
uses the hash, so it behaves the same at a project path as at a domain root.

For GitHub Pages, push the repository and set Settings, Pages, Source to GitHub
Actions. The first deploy works on the committed snapshot with no database and
no secrets, which is a good way to check the plumbing before pointing anything
real at it.

The workflow refuses to deploy a snapshot whose profile is not `public`, so an
organiser export cannot go out by accident.

To check a project-path deploy locally first, since that is where relative URLs
usually break:

```bash
mkdir -p /tmp/pages/scipy-india-organizing-tracker && cp -R web/public/* /tmp/pages/scipy-india-organizing-tracker/
python -m http.server 8000 --directory /tmp/pages
```

## Live mode is a different thing

```bash
cocoindex -d src update -L scipy_india_kg.main
```

This keeps Neo4j current and nothing else. It re-runs every
`LIVE_REFRESH_SECONDS`, 20 by default, and memoisation makes a cycle with no
edits nearly free.

What it does not touch is the dashboard export or the vector indexes, so after
an edit the graph and the dashboard disagree. Live mode is for working on the
pipeline; `./scripts/refresh.sh --watch` is for working on the notes.

## If you are downloading the Doc by hand

With `MEETING_NOTES_SOURCE=local` the pipeline reads every note file in
`data/meeting_notes/`. Downloading the Doc again usually gives you a new
filename, so `SciPy India 2026 Meeting Notes (1).md` lands beside the one
already there, both get read, and every meeting appears twice.

That is an error rather than a silent merge: two files claiming the same meeting
date and title stops the run and names both filenames. Overwriting works, and so
does deleting the old file first, since CocoIndex removes what a deleted file
contributed.

Connecting the Doc directly makes the whole problem go away. See
[Connecting the sources](connecting-sources.md).
