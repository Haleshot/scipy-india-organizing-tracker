#!/usr/bin/env python3
"""Report whether the graph is current with the notes, without running anything.

`refresh.sh --check` needs to answer "is this stale?" without the pipeline,
because a flag that promises to write nothing has to keep that promise. The
comparison is done here rather than in shell because BSD and GNU `find`
disagree about `-newermt`, and getting that wrong silently reports everything
as current.

Exit status is 0 when the graph is current and 1 when at least one note file
has changed since the last build.
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTE_SUFFIXES = (".md", ".markdown", ".txt")


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def built_at() -> datetime.datetime | None:
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "scipyindia"),
        ),
        connection_timeout=5,
    )
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            record = session.run(
                "MATCH (b:GraphBuild {id: 'singleton'}) RETURN b.built_at AS built_at"
            ).single()
    finally:
        driver.close()
    if not record or record["built_at"] is None:
        return None
    return record["built_at"].to_native()


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    directory = Path(os.environ.get("MEETING_NOTES_DIR", "./data/meeting_notes"))

    try:
        built = built_at()
    except Exception as error:  # noqa: BLE001 - the caller wants a message, not a trace
        print(f"cannot reach Neo4j: {error}", file=sys.stderr)
        return 2

    if built is None:
        print("no build record: the pipeline has not run against this database")
        return 1

    cutoff = built.timestamp()
    changed = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in NOTE_SUFFIXES and path.stat().st_mtime > cutoff
    )

    local = built.astimezone()
    if not changed:
        print(f"graph is current with the notes (built {local:%Y-%m-%d %H:%M})")
        return 0

    print(f"{len(changed)} note file(s) changed since the graph was built {local:%Y-%m-%d %H:%M}:")
    for path in changed:
        when = datetime.datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        print(f"  {path} (modified {when:%Y-%m-%d %H:%M})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
