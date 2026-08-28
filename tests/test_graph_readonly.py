"""The retrieval layer cannot write, and is not merely trusted not to.

Every query runs under ``RoutingControl.READ``. Neo4j rejects a write inside a
read transaction, so this is enforced by the database rather than by review.
These tests prove it instead of asserting it in a docstring.
"""

import inspect
import re

import pytest

from neo4j_support import requires_neo4j
from scipy_india_kg.graph import cypher, service

WRITE_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV)\b", re.IGNORECASE
)


def test_no_query_in_the_retrieval_layer_contains_a_write_clause():
    statements = {
        name: value
        for name, value in vars(cypher).items()
        if isinstance(value, str) and not name.startswith("__")
    }
    assert statements, "expected to find query constants"
    offenders = {name: WRITE_CLAUSES.findall(text) for name, text in statements.items()}
    assert {name: found for name, found in offenders.items() if found} == {}


def test_every_query_runs_under_read_routing():
    source = inspect.getsource(service.OrganizerGraph._rows)
    assert "RoutingControl.READ" in source
    # _rows is the only place the driver is touched, so nothing can bypass it.
    class_source = inspect.getsource(service.OrganizerGraph)
    assert class_source.count("execute_query") == 1


def test_the_mcp_server_exposes_no_write_or_raw_cypher_tool():
    from scipy_india_kg.mcp import server as mcp_server

    source = inspect.getsource(mcp_server)
    for forbidden in ("run_cypher", "execute_cypher", "write_", "create_", "update_", "delete_"):
        assert f"async def {forbidden}" not in source
    assert "read_only_hint=True" in source


@requires_neo4j
@pytest.mark.asyncio
async def test_neo4j_itself_refuses_a_write_on_this_connection(graph):
    """The real guarantee: even a write sent deliberately down this path fails."""
    from neo4j.exceptions import Neo4jError

    with pytest.raises(Neo4jError) as caught:
        await graph._rows("CREATE (n:ShouldNeverExist {id: 'x'}) RETURN n")
    assert "write" in str(caught.value).lower()


@requires_neo4j
@pytest.mark.asyncio
async def test_nothing_was_created_by_that_attempt(graph):
    rows = await graph._rows("MATCH (n:ShouldNeverExist) RETURN count(n) AS count")
    assert rows[0]["count"] == 0
