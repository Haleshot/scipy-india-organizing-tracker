"""The MCP server, driven through a real client over stdio.

Not a unit test of the tool functions: this launches ``python -m
scipy_india_kg.mcp`` as a subprocess and talks MCP to it, so what it asserts is
what an MCP client actually receives. Skipped when Neo4j is not up.
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from neo4j_support import requires_neo4j

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [requires_neo4j, pytest.mark.asyncio]

SERVER_ENV = {
    "PYTHONPATH": str(REPO_ROOT / "src"),
    "TOKENIZERS_PARALLELISM": "false",
}

EXPECTED_TOOLS = {
    "describe_graph",
    "list_recent_meetings",
    "get_meeting_context",
    "list_open_tasks",
    "list_unassigned_tasks",
    "get_task_history",
    "get_person_context",
    "get_workgroup_context",
    "list_recent_decisions",
    "find_interested_unassigned_volunteers",
}


@asynccontextmanager
async def mcp_session():
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "scipy_india_kg.mcp"],
        cwd=str(REPO_ROOT),
        # PYTHONPATH rather than relying on the editable install: the subprocess
        # must import the package whether or not `pip install -e .` is in effect,
        # and this is exactly what the documented client config does too.
        env={**os.environ, **SERVER_ENV},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session, tool: str, **arguments):
    result = await session.call_tool(tool, arguments)
    assert not result.is_error, f"{tool} returned an error: {result.content}"
    payload = result.structured_content
    if payload is None:
        return json.loads(result.content[0].text)
    return payload.get("result", payload)


# Deliberately not a fixture. pytest-asyncio enters and exits an async
# generator fixture in different tasks, and anyio cancel scopes (which
# stdio_client uses) cannot cross tasks. Opening the session inside each test
# keeps both ends in one task. It costs one subprocess launch per test, which
# at this size is a second.


async def test_the_server_starts_and_identifies_itself():
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "scipy_india_kg.mcp"],
        cwd=str(REPO_ROOT),
        env={**os.environ, **SERVER_ENV},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        init = await client.initialize()
        assert init.server_info.name == "scipy-india-organizing"


async def test_every_expected_tool_is_registered():
    async with mcp_session() as session:
        tools = {tool.name for tool in (await session.list_tools()).tools}
        assert EXPECTED_TOOLS <= tools


async def test_every_tool_is_annotated_read_only():
    async with mcp_session() as session:
        for tool in (await session.list_tools()).tools:
            assert tool.annotations is not None, f"{tool.name} has no annotations"
            assert tool.annotations.read_only_hint is True, f"{tool.name} is not marked read-only"
            assert tool.annotations.destructive_hint is False


async def test_no_write_or_raw_cypher_tool_is_exposed():
    async with mcp_session() as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        for forbidden in ("run_cypher", "execute_cypher", "query", "write", "create_node"):
            assert forbidden not in names
        assert not any(name.startswith(("create_", "update_", "delete_", "set_")) for name in names)


async def test_asking_for_a_write_tool_gets_an_error_not_a_write():
    """An agent that tries to run Cypher finds there is nothing to run it with."""
    async with mcp_session() as session:
        result = await session.call_tool("run_cypher", {"query": "CREATE (n:Hack)"})
        assert result.is_error
        assert "unknown tool" in str(result.content).lower()


async def test_describe_graph_reports_provenance_and_capability():
    async with mcp_session() as session:
        report = await call(session, "describe_graph")
        assert report["node_counts"]["Meeting"] >= 5
        assert report["build"]["notes_source"] in {"local", "google_drive"}
        assert report["search_strategy"] in {"full_text", "vector", "hybrid", "unavailable"}


async def test_list_open_tasks():
    async with mcp_session() as session:
        tasks = await call(session, "list_open_tasks")
        assert tasks
        assert all(task["status"] != "done" for task in tasks)


async def test_list_unassigned_tasks():
    async with mcp_session() as session:
        tasks = await call(session, "list_unassigned_tasks")
        assert tasks
        assert all(task["owners"] == [] for task in tasks)


async def test_list_unassigned_tasks_can_be_scoped_to_a_workgroup():
    async with mcp_session() as session:
        tasks = await call(session, "list_unassigned_tasks", workgroup="Website & Tech")
        assert all(task["workgroup"] == "website-tech" for task in tasks)


async def test_get_person_context():
    async with mcp_session() as session:
        person = await call(session, "get_person_context", name="Priya Vasudevan")
        assert person["name"] == "Priya Vasudevan"
        assert person["member_of"]
        assert isinstance(person["open_tasks"], list)


async def test_get_workgroup_context():
    async with mcp_session() as session:
        context = await call(session, "get_workgroup_context", workgroup="Website & Tech")
        assert context["slug"] == "website-tech"
        assert context["members"]
        assert context["open_tasks"]
        assert context["recent_meetings"]


async def test_get_meeting_context_carries_status_transitions():
    async with mcp_session() as session:
        context = await call(session, "get_meeting_context")
        assert context["meeting"]["source_ref"]
        assert context["attendees"]
        assert any(item["previous_status"] for item in context["action_items"])


async def test_get_task_history_returns_provenance():
    async with mcp_session() as session:
        details = await call(session, "get_task_history", task="Port the 2025 site template")
        assert details[0]["created_in"] is not None
        assert [point["status"] for point in details[0]["history"]] == [
            "open",
            "blocked",
            "in_progress",
        ]


async def test_find_interested_unassigned_volunteers():
    async with mcp_session() as session:
        waiting = await call(session, "find_interested_unassigned_volunteers", workgroup="program")
        assert waiting
        assert all(entry["workgroup"] == "program" for entry in waiting)


async def test_list_recent_decisions():
    async with mcp_session() as session:
        decisions = await call(session, "list_recent_decisions", limit=5)
        assert decisions
        assert all(decision["meetings"] for decision in decisions)


async def test_search_is_registered_only_when_an_index_can_serve_it():
    async with mcp_session() as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        report = await call(session, "describe_graph")
        if report["search_strategy"] == "unavailable":
            assert "search_organizing_graph" not in names
        else:
            assert "search_organizing_graph" in names
            result = await call(
                session, "search_organizing_graph", query="code of conduct", limit=5
            )
            assert result["strategy"] == report["search_strategy"]
            assert result["hits"]


async def test_the_search_tool_description_names_its_strategy():
    async with mcp_session() as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        search = tools.get("search_organizing_graph")
        if search is None:
            pytest.skip("no search index built")
        report = await call(session, "describe_graph")
        assert report["search_strategy"] in search.description
