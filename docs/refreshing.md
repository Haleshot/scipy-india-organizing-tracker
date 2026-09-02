# Refreshing the graph

One command rebuilds everything that derives from the sources:

```bash
./scripts/refresh.sh
```

It runs three stages in order, because they depend on each other. The graph is
built from the notes and the tracker; the search indexes are built from the
graph; the dashboard's data file is exported from the graph and checked before
it is written. Running them out of order gives you a dashboard describing a
graph that no longer exists.

Everything is incremental. A meeting section whose text has not changed is
matched against its cached extraction and skipped, and the index builder
re-embeds only nodes whose indexed text moved. A refresh after one edited
meeting takes about as long as a refresh after none.

A real run looks like this:

```
1/3  Graph
  ✅ process_note_file: 1 total | 1 reprocessed
  Issue: 43 -> 43
  Task: 22 -> 23

2/3  Search indexes
  vector    task_embedding_index    1 embedded, 22 already current, 384 dims

3/3  Dashboard snapshot
  Wrote web/public/data/graph.json: 5 meetings, 3 people, 23 tasks
  privacy checks passed
```

## The flags

`--check` reports what is stale and writes nothing, which is what you want in
CI or when you are not sure whether somebody else already ran it.

`--reset` empties the graph and rebuilds from scratch. Reach for it after
changing something structural, like a workgroup slug or the shape of a node,
where incremental updates leave the old version behind.

`--no-search` skips the indexes, `--force` re-embeds everything, and `--watch`
re-runs the whole thing whenever the notes change. `--watch` needs `fswatch`
(`brew install fswatch`).

## Live mode is a different thing

```bash
cocoindex -d src update -L scipy_india_kg.main
```

This keeps **Neo4j** current and nothing else. It re-runs the pipeline every
`LIVE_REFRESH_SECONDS`, 20 by default, and memoisation makes a cycle with no
edits nearly free.

What it does not touch is the dashboard export or the vector indexes. After an
edit, the graph and `graph.json` disagree, and the dashboard is the half you are
usually looking at. So live mode is for working on the pipeline, and
`./scripts/refresh.sh --watch` is for working on the notes.

## If you are downloading the Doc by hand

With `MEETING_NOTES_SOURCE=local`, the pipeline reads every note file in
`data/meeting_notes/`. Downloading the Doc again usually produces a new
filename, so `SciPy India 2026 Meeting Notes (1).md` lands next to the one
already there, both get read, and every meeting appears twice.

The pipeline refuses that rather than merging quietly: two files claiming the
same meeting date and title is an error naming both filenames. Overwriting the
existing file is fine, and so is deleting the old one first, because CocoIndex
removes what a deleted file contributed. To stop thinking about it, set
`MEETING_NOTES_FILE` in `.env` to one canonical name and always save over it.

Connecting the Doc directly removes this problem entirely. See
[Connecting the sources](connecting-sources.md).
