"""Search: capability detection, graceful degradation, and read-only enforcement.

The interesting cases are the ones where infrastructure is missing. A graph with
no indexes must say so rather than error; a graph with vector indexes but no
embedding provider must fall back to full text rather than return nothing.
"""

import pytest

from neo4j_support import requires_neo4j
from scipy_india_kg.graph.capabilities import GraphCapabilities, SearchCapability
from scipy_india_kg.graph.search_text import is_local_model, lucene_safe

ALL_LABELS = frozenset({"Meeting", "Task", "Decision", "Workgroup"})


# --------------------------------------------------------------------------- #
# Capability detection, no database needed
# --------------------------------------------------------------------------- #


def test_no_index_means_no_search():
    assert GraphCapabilities().strategy is SearchCapability.UNAVAILABLE
    assert GraphCapabilities().searchable_labels == ()


def test_full_text_alone_is_enough():
    caps = GraphCapabilities(full_text_labels=ALL_LABELS)
    assert caps.strategy is SearchCapability.FULL_TEXT
    assert set(caps.searchable_labels) == ALL_LABELS


def test_vector_indexes_without_a_provider_fall_back_to_full_text():
    """The index exists but nothing can embed the query, so it is unusable."""
    caps = GraphCapabilities(
        full_text_labels=ALL_LABELS,
        vector_labels=ALL_LABELS,
        embedded_labels=ALL_LABELS,
        embeddings_configured=False,
    )
    assert caps.strategy is SearchCapability.FULL_TEXT


def test_vector_indexes_without_embedded_nodes_fall_back_to_full_text():
    """The index was created but the pipeline never wrote vectors into it."""
    caps = GraphCapabilities(
        full_text_labels=ALL_LABELS,
        vector_labels=ALL_LABELS,
        embedded_labels=frozenset(),
        embeddings_configured=True,
    )
    assert caps.strategy is SearchCapability.FULL_TEXT


def test_both_present_gives_hybrid():
    caps = GraphCapabilities(
        full_text_labels=ALL_LABELS,
        vector_labels=ALL_LABELS,
        embedded_labels=ALL_LABELS,
        embeddings_configured=True,
    )
    assert caps.strategy is SearchCapability.HYBRID


def test_partial_vector_coverage_does_not_claim_hybrid():
    """Mixing cosine scores for one label with Lucene scores for another gives
    numbers that cannot be ranked against each other."""
    caps = GraphCapabilities(
        full_text_labels=ALL_LABELS,
        vector_labels=frozenset({"Task"}),
        embedded_labels=frozenset({"Task"}),
        embeddings_configured=True,
    )
    assert caps.strategy is SearchCapability.FULL_TEXT


def test_volunteer_applications_are_never_searchable():
    from scipy_india_kg.graph.capabilities import FULL_TEXT_INDEXES, VECTOR_INDEXES
    from scipy_india_kg.graph.search_text import INDEXED_PROPERTIES, TEXT_BUILDERS

    for mapping in (FULL_TEXT_INDEXES, VECTOR_INDEXES, INDEXED_PROPERTIES, TEXT_BUILDERS):
        assert "VolunteerApplication" not in mapping
        assert "Person" not in mapping


def test_lucene_syntax_in_a_question_is_neutralised():
    assert lucene_safe("what about the CFP?") == "what about the CFP"
    assert lucene_safe('site:example.com AND "quoted"') == "site example.com AND quoted"
    assert lucene_safe("!!!") == "*", "an all-punctuation query must still be valid Lucene"


def test_local_models_are_told_apart_from_provider_strings():
    assert is_local_model("Snowflake/snowflake-arctic-embed-xs")
    assert is_local_model("all-MiniLM-L6-v2")
    assert not is_local_model("openai/text-embedding-3-small")


# --------------------------------------------------------------------------- #
# Against the live graph
# --------------------------------------------------------------------------- #

pytestmark_live = [requires_neo4j, pytest.mark.asyncio]


@requires_neo4j
@pytest.mark.asyncio
async def test_search_reports_the_strategy_it_used(graph):
    result = await graph.search("code of conduct", limit=5)
    assert result.strategy in {"full_text", "vector", "hybrid", "unavailable"}
    if result.strategy == "unavailable":
        assert "build_search_indexes" in result.note
        return
    assert result.hits
    assert all(hit.retrieval == result.strategy for hit in result.hits)


@requires_neo4j
@pytest.mark.asyncio
async def test_search_finds_the_obvious_thing(graph):
    result = await graph.search("code of conduct", limit=6)
    if result.strategy == "unavailable":
        pytest.skip("no search index built")
    titles = " ".join(hit.title.lower() for hit in result.hits)
    assert "code of conduct" in titles


@requires_neo4j
@pytest.mark.asyncio
async def test_search_can_be_narrowed_to_one_kind(graph):
    result = await graph.search("sponsoring", limit=5, kinds=["decision"])
    if result.strategy == "unavailable":
        pytest.skip("no search index built")
    assert all(hit.kind == "decision" for hit in result.hits)


@requires_neo4j
@pytest.mark.asyncio
async def test_a_nonsense_query_returns_nothing_rather_than_erroring(graph):
    result = await graph.search("zzzqqqxxx", limit=5)
    assert result.strategy != "unavailable" or result.note
