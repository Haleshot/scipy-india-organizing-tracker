# Weekly workflow

I download the latest version of the notes Doc as Markdown into
`data/meeting_notes/`, replacing the file that is already there. Then:

```bash
./scripts/refresh.sh
```

That is the whole thing. CocoIndex notices which meeting sections changed and
re-extracts only those; the index builder re-embeds only the nodes whose text
changed; the exporter rewrites `web/public/data/graph.json`. It prints what
moved, so a refresh after a real meeting looks like this:

```
1/3  Graph
  ✅ process_note_file: 1 total | 1 reprocessed
  OpenTasks: 15 -> 16
  Task: 22 -> 23

2/3  Search indexes
  vector    task_embedding_index    1 embedded, 22 already current, 384 dims

3/3  Dashboard snapshot
  Wrote web/public/data/graph.json: 5 meetings, 10 people (5 withheld), 23 tasks
  privacy checks passed
```

`./scripts/refresh.sh --check` reports what is stale without changing anything.
`--no-search` skips the indexes, `--force` re-embeds everything, and `--watch`
re-runs the whole refresh whenever the notes change, which needs `fswatch`.

### About the filename

Downloading the Doc again usually gives you a new name: `SciPy India 2026
Meeting Notes (1).md` lands next to the one already there. Both get read, every
meeting appears twice, and nothing looks wrong until you count the open tasks. I
hit this while building the refresh script and the graph quietly went from 22
tasks to 50.

So the pipeline refuses it now. Two files claiming the same meeting date and
title is an error with both filenames in the message, not a silent merge. If you
overwrite the existing file, nothing special happens and the refresh is
incremental as usual. If you delete the old export first and the new one has a
different name, that also works: CocoIndex removes what the deleted file
contributed and adds the new file's meetings, so the graph ends up the same
either way.

If you would rather not think about it, set `MEETING_NOTES_FILE` in `.env` to
one canonical filename and always save over it. Anything else in the directory
is then ignored.

## What each piece is doing

Neo4j holds the private graph: meetings, people, action items, decisions,
workgroups and volunteer applications, including contact details and the
free-text answers people gave on the form. Nothing published ever comes from
here directly.

CocoIndex is the pipeline that fills it. It reads the notes, splits them into
meetings, extracts structure from each one, works out which names refer to the
same person, and declares the resulting nodes and edges. Because it memoises per
meeting section, editing one meeting re-extracts one meeting and leaves the rest
of the graph alone. Delete a file and its contributions come out cleanly.

The exporter is there because GitHub Pages is static and public, and the graph is
neither. `scripts/export_public_snapshot.py` queries Neo4j and writes a JSON file
containing only fields named in an allowlist, which makes it the gate between
the two halves of the project.

Then there is the MCP server, the other reader. It connects to the same Neo4j,
exposes eleven read-only tools, and lets an agent answer "what is still open in
Website" from the graph rather than by grepping the notes file. It runs on
your laptop and is not part of the Pages deployment.

Search indexes sit outside all of that and are optional. Full-text needs nothing
at all. Adding vectors turns the MCP server's search tool into hybrid retrieval,
and since the model runs locally there is still no API key involved. They need
rebuilding when the notes change, which `./scripts/refresh.sh` handles.

To stop everything: `docker compose down`. The graph rebuilds from the notes in
a few seconds, so throwing the container away costs nothing.

## Live mode

```bash
cocoindex -d src update -L scipy_india_kg.main
```

This keeps **Neo4j** current and nothing else. It re-runs the pipeline every
`LIVE_REFRESH_SECONDS` (20 by default); memoisation makes a cycle with no edits
cost almost nothing, and a cycle after one edited meeting re-extracts that
meeting only. Polling rather than filesystem events, because person resolution
has to see every name before it can decide which ones are the same person, so
there is nothing useful to do with a single changed file on its own.

The dashboard snapshot and the vector embeddings are not touched by `-L`. I
checked: after an edit the graph said two unassigned tasks while `graph.json`
still said three. So `-L` is for working on the pipeline, and this is for
working on the notes:

```bash
./scripts/refresh.sh --watch
```

That re-runs the full refresh on every change, so the graph, the search indexes
and the dashboard all stay current together. It needs `fswatch`
(`brew install fswatch`).
