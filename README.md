# SciPy India organizing tracker

We take notes in a Google Doc during organising calls and file tasks as issues
on the planning repo. This reads both and keeps track of who owns what, what is
still open, and which volunteer role it belongs to, so handing work to people
stops being a memory exercise.

```
meeting notes ->                     +-> sanitized export -> dashboard
                 CocoIndex -> Neo4j -+
GitHub issues ->                     +-> read-only MCP server -> your agent
```

Two readers, and they never talk to each other. The dashboard is built from an
export that copies only allowlisted fields, so it is safe to publish. The MCP
server sits next to the private database on a laptop and is not deployed.

Right now it runs on the three organisers listed at
[scipy.in/2026/team](https://scipy.in/2026/team). Volunteer sign-ups exist, but
nobody has been contacted yet, so none of that data is in this repository and
`data/volunteers/applications.json` is empty on purpose. The thirteen volunteer
roles in `config/workgroups.yaml` are the real ones from the sign-up form.

No model runs unless you switch one on. See
[How AI is used](docs/how-ai-is-used.md).

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d --wait
./scripts/refresh.sh
python -m http.server 8000 --directory web/public
```

That builds a graph from the notes in `data/meeting_notes/` with no credentials
needed. Pointing it at the team's real Doc and the issue tracker is
[Connecting the sources](docs/connecting-sources.md).

After that, `./scripts/refresh.sh` is the whole loop. It rebuilds the graph, the
search indexes and the dashboard data, and says what changed.

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
| [Keeping it current](docs/refreshing.md) | What to run after a meeting, scheduling it, putting it online |
| [Running it on Neo4j Desktop](docs/neo4j-desktop.md) | The graph in a query editor, and useful Cypher |
| [Asking questions](docs/asking-questions.md) | The thirteen tools, and connecting Claude |
| [The graph model](docs/graph-model.md) | Node labels, task identity, provenance |
| [Design notes](docs/design.md) | The dashboard's constraints, and what is absent on purpose |

## Layout

```
config/workgroups.yaml     the thirteen volunteer roles
config/people.yaml         the organisers, and their GitHub handles
data/meeting_notes/        notes to build from when not using Drive
src/scipy_india_kg/        pipeline, retrieval layer, MCP server, CLI
scripts/refresh.sh         the one command
scripts/check_drive.py     says which Drive setup step is missing
web/public/                the dashboard, deployed as-is
docs/                      this documentation, built by Zensical
tests/                     the Neo4j ones skip when it is not running
```

## Tests

```bash
pytest -q
ruff check . && ruff format --check .
```

Most of the suite needs nothing. The rest need a populated Neo4j and skip
cleanly without one.
