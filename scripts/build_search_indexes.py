#!/usr/bin/env python3
"""Build the optional search indexes the MCP server and CLI can use.

Two tiers, and the second is genuinely optional:

**Full-text** (default). Four Neo4j full-text indexes over meeting titles,
topics and summaries; action-item descriptions; decision statements; and
workgroup names and descriptions. No models, no API key, no embeddings. This is
what makes ``search_organizing_graph`` work at all.

**Vector** (``--embeddings``). Adds an ``embedding`` property and a vector index
per label, which turns the same tool into hybrid retrieval. The default model is
sentence-transformers running locally, so this needs no API key either; set
SEARCH_EMBEDDING_MODEL to a LiteLLM string to use a hosted provider instead.

Volunteer applications are indexed by neither. Somebody's free-text answer about
themselves is not something to make semantically searchable by default.

    python scripts/build_search_indexes.py
    python scripts/build_search_indexes.py --embeddings
    python scripts/build_search_indexes.py --drop
    python scripts/build_search_indexes.py --status

This writes to Neo4j, which is why it is a script and not an MCP tool.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from scipy_india_kg.graph.capabilities import (  # noqa: E402
    FULL_TEXT_INDEXES,
    VECTOR_INDEXES,
)
from scipy_india_kg.graph.search_text import (  # noqa: E402
    DEFAULT_LOCAL_MODEL,
    INDEXED_PROPERTIES,
    TEXT_BUILDERS,
    embed_texts,
    embedding_model_name,
)


def existing_vector_dimensions(session, index_name: str) -> int | None:
    """The dimension an existing vector index was created with, or None.

    `CREATE VECTOR INDEX ... IF NOT EXISTS` silently keeps the old index when
    one already exists, so switching to a model with a different vector width
    leaves an index that can never match the vectors being written into it. The
    query embedding is a different length again, and search quietly returns
    nothing useful. Better to notice here.
    """
    row = session.run(
        """
        SHOW INDEXES YIELD name, type, options
        WHERE name = $name AND type = 'VECTOR'
        RETURN options AS options
        """,
        name=index_name,
    ).single()
    if not row or not row["options"]:
        return None
    config = row["options"].get("indexConfig") or {}
    dimensions = config.get("vector.dimensions")
    return int(dimensions) if dimensions is not None else None


PRIMARY_KEY = {
    "Meeting": "id",
    "Task": "id",
    "Decision": "statement",
    "Workgroup": "slug",
}


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def create_full_text(session) -> None:
    for label, index in FULL_TEXT_INDEXES.items():
        properties = ", ".join(f"n.{prop}" for prop in INDEXED_PROPERTIES[label])
        session.run(
            f"CREATE FULLTEXT INDEX {index} IF NOT EXISTS FOR (n:{label}) ON EACH [{properties}]"
        )
        print(f"  full-text {index:32} on {label}({', '.join(INDEXED_PROPERTIES[label])})")


def write_embeddings(
    session, model: str, *, force: bool = False, recreate: bool = False
) -> tuple[int, int]:
    """Embed the nodes whose indexed text changed. Returns (embedded, skipped).

    Each node stores a hash of the exact text that was embedded alongside the
    vector, so a refresh after one edited meeting re-embeds that meeting and
    leaves the other forty-nine nodes alone. The model name goes into the hash
    too: switching models has to invalidate everything, and silently mixing
    vectors from two models would produce nonsense rankings rather than an
    error.
    """
    embedded = skipped = 0
    for label, builder in TEXT_BUILDERS.items():
        key = PRIMARY_KEY[label]
        rows = session.run(f"MATCH (n:{label}) RETURN n").data()
        if not rows:
            print(f"  {label}: no nodes, skipping")
            continue
        all_nodes = [row["n"] for row in rows]

        pending = []
        for node in all_nodes:
            text = builder(node)
            digest = hashlib.sha256(f"{model}\x1f{text}".encode()).hexdigest()[:32]
            if not force and node.get("embedding_hash") == digest and node.get("embedding"):
                skipped += 1
                continue
            pending.append((node, text, digest))

        if not pending:
            print(f"  {label}: {len(all_nodes)} nodes already current")
            continue

        nodes = [item[0] for item in pending]
        texts = [item[1] for item in pending]
        vectors = embed_texts(texts, model)
        dimensions = len(vectors[0])

        index_name = VECTOR_INDEXES[label]
        current = existing_vector_dimensions(session, index_name)
        if current is not None and current != dimensions:
            if not recreate:
                raise SystemExit(
                    f"\n{index_name} was built for {current}-dimensional vectors and "
                    f"{model} produces {dimensions}. Neo4j will not widen an existing "
                    f"vector index, so it has to be recreated.\n\n"
                    f"    python scripts/build_search_indexes.py --embeddings --recreate\n\n"
                    f"(or --drop first, if you would rather start from nothing)."
                )
            print(f"  dimension change {current} -> {dimensions}, recreating {index_name}")
            session.run(f"DROP INDEX {index_name} IF EXISTS")

        session.run(
            f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (n:{label}) ON n.embedding
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {dimensions},
                `vector.similarity_function`: 'cosine'
            }}}}
            """
        )
        session.run(
            f"""
            UNWIND $rows AS row
            MATCH (n:{label} {{{key}: row.key}})
            CALL db.create.setNodeVectorProperty(n, 'embedding', row.embedding)
            SET n.embedding_hash = row.hash
            """,
            rows=[
                {"key": node[key], "embedding": vector, "hash": digest}
                for (node, _text, digest), vector in zip(pending, vectors, strict=True)
            ],
        )
        embedded += len(nodes)
        untouched = len(all_nodes) - len(nodes)
        suffix = f", {untouched} already current" if untouched else ""
        print(f"  vector    {index_name:32} {len(nodes)} embedded{suffix}, {dimensions} dims")
    return embedded, skipped


def drop_all(session) -> None:
    for index in (*FULL_TEXT_INDEXES.values(), *VECTOR_INDEXES.values()):
        session.run(f"DROP INDEX {index} IF EXISTS")
        print(f"  dropped {index}")
    session.run("MATCH (n) WHERE n.embedding IS NOT NULL REMOVE n.embedding, n.embedding_hash")
    print("  removed embedding properties")


def show_status(session) -> None:
    rows = session.run(
        """
        SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, state
        WHERE type IN ['FULLTEXT', 'VECTOR'] AND entityType = 'NODE'
        RETURN name, type, labelsOrTypes, state ORDER BY type, name
        """
    ).data()
    if not rows:
        print("  no search indexes")
    for row in rows:
        print(f"  {row['type']:9} {row['name']:32} {row['labelsOrTypes']} {row['state']}")
    embedded = session.run(
        "MATCH (n) WHERE n.embedding IS NOT NULL "
        "RETURN labels(n)[0] AS label, count(*) AS count ORDER BY label"
    ).data()
    print("  embedded nodes:", {row["label"]: row["count"] for row in embedded} or "none")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", action="store_true", help="also build vector indexes")
    parser.add_argument("--drop", action="store_true", help="remove every search index")
    parser.add_argument("--status", action="store_true", help="report and exit")
    parser.add_argument("--model", default=None, help="embedding model (default: local)")
    parser.add_argument(
        "--force", action="store_true", help="re-embed every node, not only changed ones"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="drop and rebuild any vector index whose dimensions no longer match the model",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "scipyindia"),
        ),
    )
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            if args.status:
                print("Search indexes:")
                show_status(session)
                return 0
            if args.drop:
                print("Dropping search indexes:")
                drop_all(session)
                return 0

            print("Creating full-text indexes:")
            create_full_text(session)

            if args.embeddings:
                model = args.model or embedding_model_name() or DEFAULT_LOCAL_MODEL
                print(f"\nEmbedding with {model} (first run downloads the model):")
                embedded, skipped = write_embeddings(
                    session, model, force=args.force, recreate=args.recreate
                )
                if embedded:
                    print(f"\nEmbedded {embedded} nodes, left {skipped} unchanged.")
                else:
                    print(f"\nEvery one of the {skipped} embedded nodes was already current.")
                print(
                    f"Set {'SEARCH_EMBEDDING_MODEL'}={model} in .env so the MCP server and CLI "
                    "embed queries with the same model. Without it they stay on full text."
                )
            else:
                print("\nFull-text search is ready. Add --embeddings for hybrid retrieval.")
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
