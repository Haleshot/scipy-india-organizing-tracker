# Get started

You need Docker and Python 3.11 or newer. From a clean shell:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d --wait
./scripts/refresh.sh
python -m http.server 8000 --directory web/public
```

Open <http://localhost:8000>. `docker compose up -d --wait` blocks until Neo4j
answers on Bolt, so the refresh never races a database that is still booting,
and it takes about seven seconds. The refresh builds the graph, the search
indexes and the dashboard snapshot in that order.

If you also want an agent to be able to query the graph, run
`python scripts/print_mcp_config.py --write` and restart Claude Code in this
directory. That part is optional and covered further down.
