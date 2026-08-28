"""What this graph can actually do, probed at connect time.

NeoCarta's MCP server asks the database what search indexes exist before it
registers a single search tool, and picks hybrid, vector or full-text per label
based on the answer. That is the pattern worth stealing: retrieval quality
depends on infrastructure the operator may or may not have set up, and an agent
should be told which one it is getting rather than discovering it through bad
results.

Here the probe answers three things:

* which full-text indexes exist (created by ``scripts/build_search_indexes.py``,
  free, no models);
* which vector indexes exist and whether the nodes actually carry embeddings;
* how the graph was built, read from the ``GraphBuild`` singleton the pipeline
  writes.

Nothing here writes, and nothing here fails hard: a graph with no indexes at
all reports ``strategy="unavailable"`` and the search tool says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from neo4j import AsyncDriver, RoutingControl

# Full-text index names, one per searchable label. Kept in one place so the
# index builder, the probe and the search queries cannot drift apart.
FULL_TEXT_INDEXES = {
    "Meeting": "meeting_full_text_index",
    "Task": "task_full_text_index",
    "Decision": "decision_full_text_index",
    "Workgroup": "workgroup_full_text_index",
}

VECTOR_INDEXES = {
    "Meeting": "meeting_embedding_index",
    "Task": "task_embedding_index",
    "Decision": "decision_embedding_index",
    "Workgroup": "workgroup_embedding_index",
}

# Volunteer applications are deliberately absent from both maps. Free-text
# answers people gave on a form are not something to make semantically
# searchable by default; an agent asking "who is good at design" should reach
# the structured skills field, not somebody's paragraph about themselves.
SEARCHABLE_LABELS = tuple(FULL_TEXT_INDEXES)

LIST_SEARCH_INDEXES = """
SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, state
WHERE type IN ['FULLTEXT', 'VECTOR'] AND entityType = 'NODE'
RETURN name, type, labelsOrTypes, state
"""

COUNT_EMBEDDED_NODES = """
MATCH (n)
WHERE n.embedding IS NOT NULL
RETURN labels(n)[0] AS label, count(*) AS count
"""

FETCH_BUILD = "MATCH (b:GraphBuild {id: 'singleton'}) RETURN b"

NODE_COUNTS = "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY label"
REL_COUNTS = "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY type"


class SearchCapability(StrEnum):
    """Retrieval strategies, best first."""

    HYBRID = "hybrid"
    VECTOR = "vector"
    FULL_TEXT = "full_text"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GraphCapabilities:
    full_text_labels: frozenset[str] = frozenset()
    vector_labels: frozenset[str] = frozenset()
    embedded_labels: frozenset[str] = frozenset()
    embeddings_configured: bool = False
    build: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def strategy(self) -> SearchCapability:
        """The best strategy every searchable label can actually support.

        Deliberately conservative: mixing hybrid results for one label with
        full-text for another gives scores that cannot be compared, so the whole
        search runs at the level the weakest label supports.
        """
        vector_ready = self.vector_labels & self.embedded_labels
        if self.embeddings_configured and vector_ready and self.full_text_labels:
            if vector_ready >= set(SEARCHABLE_LABELS) and self.full_text_labels >= set(
                SEARCHABLE_LABELS
            ):
                return SearchCapability.HYBRID
        if self.embeddings_configured and vector_ready >= set(SEARCHABLE_LABELS):
            return SearchCapability.VECTOR
        if self.full_text_labels:
            return SearchCapability.FULL_TEXT
        return SearchCapability.UNAVAILABLE

    @property
    def searchable_labels(self) -> tuple[str, ...]:
        """Labels the current strategy can reach."""
        strategy = self.strategy
        if strategy is SearchCapability.UNAVAILABLE:
            return ()
        if strategy is SearchCapability.VECTOR:
            return tuple(label for label in SEARCHABLE_LABELS if label in self.embedded_labels)
        return tuple(label for label in SEARCHABLE_LABELS if label in self.full_text_labels)


async def probe_capabilities(
    driver: AsyncDriver, database: str, *, embeddings_configured: bool = False
) -> GraphCapabilities:
    """Ask the database what it supports. Never raises on a missing feature."""
    notes: list[str] = []

    index_rows = await driver.execute_query(
        LIST_SEARCH_INDEXES,
        database_=database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda result: result.data(),
    )
    full_text: set[str] = set()
    vector: set[str] = set()
    for row in index_rows:
        labels = row.get("labelsOrTypes") or []
        if row.get("state") not in (None, "ONLINE"):
            notes.append(f"index {row['name']} is {row['state']}, not ONLINE; skipping it")
            continue
        target = full_text if row["type"] == "FULLTEXT" else vector
        target.update(labels)

    embedded_rows = await driver.execute_query(
        COUNT_EMBEDDED_NODES,
        database_=database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda result: result.data(),
    )
    embedded = {row["label"] for row in embedded_rows if row["count"]}

    build_rows = await driver.execute_query(
        FETCH_BUILD,
        database_=database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda result: result.data(),
    )
    build: dict[str, str] = {}
    if build_rows:
        for key, value in build_rows[0]["b"].items():
            build[key] = str(value)
    else:
        notes.append(
            "No GraphBuild node: this graph was not written by the current pipeline, "
            "so its source and extraction mode are unknown."
        )

    if vector and not embeddings_configured:
        notes.append(
            "Vector indexes exist but no embedding provider is configured, so search "
            "falls back to full text. Set SEARCH_EMBEDDING_MODEL to enable it."
        )
    if vector - embedded:
        notes.append(
            "Vector indexes exist for "
            + ", ".join(sorted(vector - embedded))
            + " but those nodes carry no embedding property; run "
            "scripts/build_search_indexes.py --embeddings."
        )

    return GraphCapabilities(
        full_text_labels=frozenset(full_text),
        vector_labels=frozenset(vector),
        embedded_labels=frozenset(embedded),
        embeddings_configured=embeddings_configured,
        build=build,
        notes=tuple(notes),
    )
