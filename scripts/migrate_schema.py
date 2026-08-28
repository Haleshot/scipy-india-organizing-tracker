#!/usr/bin/env python3
"""Migrate a graph built before the task-identity and Decision-edge changes.

Two things changed in the graph schema and neither is something CocoIndex can
reconcile on its own, because both are *renames*:

* ``Task`` is keyed by ``id`` (see ``scipy_india_kg.task_identity``) instead of
  ``description``. CocoIndex creates the new uniqueness constraint but leaves
  the old ``coco_uniq_Task__description`` behind, and that constraint then
  rejects the two tasks that are supposed to share a description.
* ``Meeting -[:DECIDED]-> Task`` became ``CREATED_ACTION`` / ``TOUCHED_ACTION``,
  and ``Meeting -[:RESOLVED]-> Decision`` became ``DECIDED``. The old edges are
  no longer declared by the pipeline, so nothing deletes them.

The safe order is: run this, drop the CocoIndex app state, rebuild.

    python scripts/migrate_schema.py
    cocoindex -d src drop scipy_india_kg.main   # answer: yes
    rm -rf cocoindex.db
    cocoindex -d src update scipy_india_kg.main

Idempotent: running it on an already-migrated or empty graph does nothing.
Pass --dry-run to see what it would do.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent

# Constraints that belonged to a retired primary key.
RETIRED_CONSTRAINTS = ("coco_uniq_Task__description",)

# Relationship types the pipeline no longer declares. RESOLVED was renamed to
# DECIDED; the old DECIDED (Meeting -> Task) split into CREATED_ACTION and
# TOUCHED_ACTION. Both old shapes are detected by their endpoints so a correct
# new-schema DECIDED (Meeting -> Decision) is never touched.
RETIRED_EDGES = (
    ("RESOLVED", "MATCH (:Meeting)-[r:RESOLVED]->(:Decision) RETURN count(r) AS c"),
    ("DECIDED (Meeting->Task)", "MATCH (:Meeting)-[r:DECIDED]->(:Task) RETURN count(r) AS c"),
)

DELETE_EDGES = (
    "MATCH (:Meeting)-[r:RESOLVED]->(:Decision) DELETE r",
    "MATCH (:Meeting)-[r:DECIDED]->(:Task) DELETE r",
)


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without changing anything")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "scipyindia"),
        ),
    )
    changed = 0
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            existing = {
                record["name"] for record in session.run("SHOW CONSTRAINTS YIELD name RETURN name")
            }
            for name in RETIRED_CONSTRAINTS:
                if name not in existing:
                    print(f"constraint {name}: already gone")
                    continue
                changed += 1
                if args.dry_run:
                    print(f"constraint {name}: would DROP")
                else:
                    session.run(f"DROP CONSTRAINT {name} IF EXISTS")
                    print(f"constraint {name}: dropped")

            for label, count_query in RETIRED_EDGES:
                count = session.run(count_query).single()["c"]
                if not count:
                    print(f"edge {label}: none")
                    continue
                changed += 1
                print(f"edge {label}: {count} {'would be deleted' if args.dry_run else 'deleted'}")
            if not args.dry_run:
                for statement in DELETE_EDGES:
                    session.run(statement)
    finally:
        driver.close()

    if changed == 0:
        print("\nNothing to migrate; the graph is already on the current schema.")
    elif args.dry_run:
        print("\nRe-run without --dry-run to apply, then drop and rebuild the CocoIndex app.")
    else:
        print("\nMigrated. Now drop and rebuild so the pipeline owns every node again:")
        print("  cocoindex -d src drop scipy_india_kg.main")
        print("  rm -rf cocoindex.db")
        print("  cocoindex -d src update scipy_india_kg.main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
