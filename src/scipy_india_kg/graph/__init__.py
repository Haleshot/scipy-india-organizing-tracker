"""Read-only retrieval over the organizing graph.

This package is the single place that knows how to ask the graph a question.
The MCP server and the ``python -m scipy_india_kg.query`` CLI are both thin
wrappers over :class:`OrganizerGraph`; neither holds Cypher of its own. That
split is borrowed from NeoCarta, which keeps its Cypher in ``_mcp/cypher``, its
result shapes in ``_mcp/models``, and mirrors every MCP tool as a CLI
subcommand that runs the same query.

Everything here reads. Queries run under ``RoutingControl.READ``, which makes
Neo4j reject a write outright rather than trusting the caller.
"""

from .capabilities import GraphCapabilities, SearchCapability, probe_capabilities
from .service import OrganizerGraph, open_graph

__all__ = [
    "GraphCapabilities",
    "OrganizerGraph",
    "SearchCapability",
    "open_graph",
    "probe_capabilities",
]
