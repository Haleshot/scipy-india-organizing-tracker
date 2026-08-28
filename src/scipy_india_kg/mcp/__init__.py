"""Read-only MCP server over the SciPy India organizing graph.

Isolated from the pipeline on purpose. Nothing in ``scipy_india_kg.main``
imports this package, and this package never writes to Neo4j: it is a second,
independent consumer of the graph CocoIndex produces, alongside the sanitized
snapshot the GitHub Pages dashboard reads.

    private sources -> CocoIndex -> Neo4j -+-> sanitized snapshot -> Pages
                                           +-> this server -> local agent
"""

from .server import build_server

__all__ = ["build_server"]
