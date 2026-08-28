# Troubleshooting

**`docker compose up` fails with a container name conflict.** An older version
of this project pinned `container_name: scipy-india-neo4j`, which collides with
anything already holding that name. Compose owns the naming now, so this only
affects checkouts from before that change:

```bash
docker rm -f scipy-india-neo4j
docker compose up -d --wait
```

**`docker compose up` fails with "port is already allocated".** Something else
is on 7474 or 7687, usually an old Neo4j container. `docker ps` will name it;
`docker rm -f <name>` and try again.

**`No module named 'scipy_india_kg'`.** The editable install's `.pth` file has
stopped being honoured, which happens on some machines. `pip install -e .` fixes
it, and `./scripts/query` and `./scripts/refresh.sh` set `PYTHONPATH` themselves
so they keep working either way.

**"The same meeting appears in more than one note file".** Two exports of the
same document are in `data/meeting_notes/`. Delete the older one, or set
`MEETING_NOTES_FILE`.

**Search returns nothing and `describe-graph` says `unavailable`.** No index has
been built. `python scripts/build_search_indexes.py`.

**Neo4j Browser will not accept the password.** It is `neo4j` / `scipyindia`,
from `NEO4J_PASSWORD` in `.env`, and the connect URL is `bolt://localhost:7687`.
The catch is that Neo4j only applies `NEO4J_AUTH` when it initialises an empty
data volume, so changing `NEO4J_PASSWORD` after the volume exists does nothing.
To change it for real, `docker compose down -v` and bring it back up. The graph
rebuilds from the notes in a few seconds.

**The graph disagrees with the notes and a refresh will not fix it.** Deleting
`cocoindex.db` on its own is not a reset. CocoIndex tracks what it declared, so
a fresh state file leaves it unable to remove nodes and edges it no longer
knows about, and you get orphans. Use `./scripts/refresh.sh --reset`, which
empties Neo4j and the state together before rebuilding.

## Running the tests

```bash
pytest -q
ruff check . && ruff format --check .
```

Most of the suite needs nothing: the workgroup registry, both note formats, task
identity and its collision cases, person resolution, the volunteer adapters,
search capability detection and the privacy guarantees on the committed
snapshot. The rest need a populated Neo4j and skip cleanly without one, so CI
stays green on a runner with no database. Those cover the retrieval layer against
the live graph, read-only enforcement, and the MCP server driven through a real
client over stdio.

For the full set, bring up Neo4j and refresh first.

## Useful Cypher queries

Sixteen of them in
[queries/organizer_queries.cypher](../queries/organizer_queries.cypher), for when
you want the raw graph rather than a typed result:

```bash
python scripts/run_queries.py --list
python scripts/run_queries.py -n unowned-tasks -n latest-changes
python scripts/run_queries.py --json > /tmp/report.json
```

Beyond the obvious ones, `latest-changes` diffs the two most recent meetings,
`task-identity-audit` lists action items that share a description and shows what
keeps them apart, and `provenance` traces every unowned open item back to the
meeting and document section it came from.

## Limitations

The LLM extraction path, the embedding person resolver and the Google Drive
source have never been run here, for want of credentials. The schemas are shared
with the tested deterministic path and the architecture follows the upstream
example, but treat a graph built that way as unverified until you have run the
eval harness against it.

The Google Sheet volunteer source is a stub. Its row mapping is written and
tested; the API call is not, and `GoogleSheetVolunteerSource.applications()`
raises `NotImplementedError` rather than pretending.

Below the explicit-ID level, task identity is a heuristic. Scoping by workgroup
and document stops the obvious collisions, but two items in one workgroup that
say the same thing still merge unless one gets an `ID:`, and rewording an item
without an ID still creates a new task. Meeting ids come from `(note_file,
date)`, so two meetings on the same date in one file are distinguished by order
rather than by anything stable.

There is no authentication, no admin UI and no write path anywhere in the
project. The notes document is the source of truth and everything else is
derived from it.
