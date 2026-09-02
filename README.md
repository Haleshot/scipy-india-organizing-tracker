# SciPy India organizing graph

Turns the SciPy India organizing notes into a small Neo4j graph, so questions
like "what is still open?" or "what did we decide about the venue?" can be
answered without rereading months of meeting notes.

The meetings stay in one Google Doc that people write during a call. A CocoIndex
pipeline reads it, and the graph it builds has two readers that never talk to
each other: a sanitized snapshot behind a static dashboard, and a read-only MCP
server your local agent can query.

```
meeting notes -> CocoIndex -> Neo4j -+-> read-only MCP server -> local agent
                                     +-> sanitized snapshot -> dashboard
```

Fixture notes and fictional volunteer applications ship with the repo, so the
whole thing runs with no credentials. The volunteer roles are real, taken from
the sign-up form; nothing else from that form is here and no applicant is named.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d --wait
./scripts/refresh.sh
python -m http.server 8000 --directory web/public
```

After that, replacing the notes export and running `./scripts/refresh.sh` is the
whole weekly loop. It rebuilds the graph, the search indexes and the dashboard
snapshot, and tells you what changed.

## Documentation

Full docs are a Zensical site in [`docs/`](docs/):

```bash
zensical serve    # http://localhost:8000
zensical build    # writes site/
```

| Page | For |
| --- | --- |
| [Reading the dashboard](docs/reading-the-dashboard.md) | What is on each page and how the numbers are worked out |
| [How AI is used](docs/how-ai-is-used.md) | Every model path is optional, and what each one would send |
| [Privacy boundary](docs/privacy.md) | What gets published and what does not |
| [Get started](docs/get-started.md) | First run from a clean shell |
| [Connecting the sources](docs/connecting-sources.md) | The Google Doc and the issue tracker |
| [Writing meeting notes](docs/writing-notes.md) | The note format, and why it is shaped that way |
| [Refreshing the graph](docs/refreshing.md) | What to run after a meeting |
| [Running it on Neo4j Desktop](docs/neo4j-desktop.md) | The graph in a query editor, and useful Cypher |
| [Asking questions](docs/asking-questions.md) | The thirteen tools, and connecting Claude |
| [Publishing](docs/publishing.md) | GitHub Pages, and evaluating the LLM extractor |
| [The graph model](docs/graph-model.md) | Node labels, task identity, provenance |
| [Design notes](docs/design.md) | The dashboard's constraints, and what is absent on purpose |

## Layout

```
config/workgroups.yaml     volunteer roles, the source of truth
data/                      fixture notes and applications
src/scipy_india_kg/        pipeline, retrieval layer, MCP server, CLI
scripts/refresh.sh         the one command
web/public/                the dashboard, deployed as-is
docs/                      this documentation, built by Zensical
tests/                     213 tests; the Neo4j ones skip without it
```

## Tests

```bash
pytest -q
ruff check . && ruff format --check .
```

Most of the suite needs nothing. The rest need a populated Neo4j and skip
cleanly without one.
