"""Shared gate for the tests that need a live, populated Neo4j.

Everything about the pipeline, the extractors and the public snapshot runs
offline. The retrieval layer and the MCP server need a real graph, so those
tests skip rather than fail when Neo4j is not up. CI stays green on a runner
with no database; locally they are real tests.
"""

import os

import pytest


def _neo4j_available() -> bool:
    try:
        from neo4j import GraphDatabase
    except ImportError:  # pragma: no cover
        return False
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    auth = (
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "scipyindia"),
    )
    try:
        driver = GraphDatabase.driver(uri, auth=auth, connection_timeout=3)
        try:
            with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
                return session.run("MATCH (m:Meeting) RETURN count(m) AS c").single()["c"] > 0
        finally:
            driver.close()
    except Exception:
        return False


requires_neo4j = pytest.mark.skipif(
    not _neo4j_available(),
    reason=(
        "needs a populated Neo4j: docker compose up -d, then "
        "cocoindex -d src update scipy_india_kg.main"
    ),
)
