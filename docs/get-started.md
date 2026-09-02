# Get started

By the end of this you will have a graph of four meetings on your machine and a
dashboard showing them. It needs Python 3.11 or newer and somewhere to run
Neo4j. No Google credentials, no API keys, no GitHub token.

## Pick where Neo4j runs

Neo4j has to run somewhere, and there are two reasonable answers. Both listen on
the same port, so pick one: they cannot both run at once.

=== "Docker"

    Nothing to install beyond Docker itself, and `docker compose down` takes it
    all away again. Best if you just want to see this work.

    ```bash
    docker compose up -d --wait
    ```

    `--wait` blocks until Neo4j answers on Bolt, which takes about seven
    seconds, so the next step never races a database that is still starting.

=== "Neo4j Desktop"

    Better if you want to poke at the graph by hand, because Desktop gives you
    a query editor and a visualiser without any extra setup. Setting it up is
    a few clicks, described in
    [Running it on Neo4j Desktop](neo4j-desktop.md).

## Build the graph

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
./scripts/refresh.sh
```

If you chose Desktop, open `.env` and set `NEO4J_PASSWORD` to the password you
gave your instance before running the refresh.

The refresh does three things in order: it builds the graph, it builds the
search indexes, and it writes the dashboard's data file. It prints what changed
at each step, and it ends by checking that nothing private got into the export.

## Look at it

```bash
python -m http.server 8000 --directory web/public
```

Open <http://localhost:8000>. The overview says how many action items are open
and how many have nobody on them. The explorer draws the graph.

Everything you are looking at came from
`data/meeting_notes/scipy-india-2026-meeting-notes.md`. Open that file, change
a task's status, save it, run `./scripts/refresh.sh` again, and watch the number
move. That loop is the whole tool.

## Let an agent query it

Optional, and worth doing if you use Claude Code.

```bash
python scripts/print_mcp_config.py --write
```

Restart your agent in this directory and it gains eleven read-only tools against
the graph, so you can ask "what is open in sponsoring and who has it" in plain
language. See [Asking questions](asking-questions.md).

## When you are done

```bash
docker compose down
```

Or stop the instance in Neo4j Desktop. Nothing is lost either way: the graph is
derived from the notes, and rebuilding it takes seconds.
