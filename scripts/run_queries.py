#!/usr/bin/env python3
"""Run the queries in queries/organizer_queries.cypher against Neo4j.

    python scripts/run_queries.py                 # every query
    python scripts/run_queries.py --list          # just the names
    python scripts/run_queries.py -n open-tasks   # one of them

Reads NEO4J_* from the environment (and from .env if present).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUERY_FILE = REPO_ROOT / "queries" / "organizer_queries.cypher"

_NAME_RE = re.compile(r"^//\s*@name:\s*(.+?)\s*$", re.MULTILINE)


def load_dotenv(path: Path) -> None:
    """Minimal .env loader. Existing environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def parse_queries(text: str) -> dict[str, str]:
    """Split the file on `// @name:` markers, in file order."""
    queries: dict[str, str] = {}
    matches = list(_NAME_RE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = "\n".join(
            line
            for line in text[match.end() : end].splitlines()
            if not line.strip().startswith("//")
        ).strip()
        if body:
            queries[match.group(1)] = body
    return queries


def render(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "-"
    return "-" if value is None or value == "" else str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--name", action="append", help="run only this query (repeatable)")
    parser.add_argument("--list", action="store_true", help="list query names and exit")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--file", type=Path, default=DEFAULT_QUERY_FILE)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    queries = parse_queries(args.file.read_text(encoding="utf-8"))

    if args.list:
        for name in queries:
            print(name)
        return 0

    selected = args.name or list(queries)
    unknown = [name for name in selected if name not in queries]
    if unknown:
        print(f"Unknown query name(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"Available: {', '.join(queries)}", file=sys.stderr)
        return 2

    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "scipyindia"),
        ),
    )
    output: dict[str, list[dict]] = {}
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            for name in selected:
                rows = [record.data() for record in session.run(queries[name])]
                output[name] = rows
                if args.json:
                    continue
                print(f"\n=== {name} ({len(rows)} rows) ===")
                for row in rows:
                    print("  " + " | ".join(f"{k}={render(v)}" for k, v in row.items()))
    finally:
        driver.close()

    if args.json:
        print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
