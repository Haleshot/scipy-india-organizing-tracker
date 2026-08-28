from pathlib import Path

import pytest

from scipy_india_kg.workgroups import load_registry

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def registry():
    return load_registry(REPO_ROOT / "config" / "workgroups.yaml")


@pytest.fixture(scope="session")
def notes_text():
    return (REPO_ROOT / "data" / "meeting_notes" / "scipy-india-2026-meeting-notes.md").read_text(
        encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Neo4j-backed tests
#
# Everything about the pipeline, the extractors and the public snapshot runs
# offline. The retrieval layer and the MCP server need a live graph, so those
# tests skip rather than fail when Neo4j is not up. That keeps CI green on a
# runner with no database while still being real tests locally.
# --------------------------------------------------------------------------- #


from neo4j_support import requires_neo4j  # noqa: E402, F401


@pytest.fixture
async def graph():
    """A connected, capability-probed OrganizerGraph."""
    from scipy_india_kg.graph import open_graph

    async with open_graph() as connected:
        yield connected
