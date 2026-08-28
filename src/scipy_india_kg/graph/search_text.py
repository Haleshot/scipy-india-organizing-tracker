"""Text handling for search: what goes into the index, and query embedding.

Two responsibilities:

* **The searchable text of a node.** One function per label, used by both the
  index builder (when it writes embeddings) and anyone who wants to know what a
  match was made against. Keeping it here means the vector and the full-text
  index see the same words.
* **Embedding a query at search time**, when an embedding provider is
  configured. Local sentence-transformers by default, because it needs no API
  key and the model is already a dependency of the pipeline; any LiteLLM model
  string works too.

``VolunteerApplication`` has no entry on purpose. Free-text answers people wrote
on a form are not something to make semantically searchable by default.
"""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any

# Lucene reserves these; a query containing them unescaped is a syntax error
# rather than a search. Same list NeoCarta strips.
_LUCENE_SPECIAL = '+-&|!(){}[]^"~*?:\\/'

# Set SEARCH_EMBEDDING_MODEL to turn on vector and hybrid retrieval. A bare
# name is treated as a sentence-transformers model and runs locally; a
# LiteLLM-style "provider/model" string goes through LiteLLM and needs that
# provider's credentials.
ENV_MODEL = "SEARCH_EMBEDDING_MODEL"
DEFAULT_LOCAL_MODEL = "Snowflake/snowflake-arctic-embed-xs"


def lucene_safe(text: str) -> str:
    """Neutralise Lucene syntax so a user's question is treated as words."""
    cleaned = "".join(" " if char in _LUCENE_SPECIAL else char for char in text)
    return " ".join(cleaned.split()) or "*"


# --------------------------------------------------------------------------- #
# What each label contributes to the index
# --------------------------------------------------------------------------- #


def meeting_text(node: dict[str, Any]) -> str:
    parts = [node.get("title") or "", node.get("summary") or "", *(node.get("topics") or [])]
    return " ".join(part for part in parts if part)


def task_text(node: dict[str, Any]) -> str:
    parts = [node.get("description") or "", node.get("due") or ""]
    return " ".join(part for part in parts if part)


def decision_text(node: dict[str, Any]) -> str:
    return node.get("statement") or ""


def workgroup_text(node: dict[str, Any]) -> str:
    parts = [node.get("name") or "", node.get("description") or ""]
    return " ".join(part for part in parts if part)


# Property lists for the full-text indexes, and the text builder for embeddings.
INDEXED_PROPERTIES = {
    "Meeting": ("title", "summary", "topics"),
    "Task": ("description", "due"),
    "Decision": ("statement",),
    "Workgroup": ("name", "description"),
}

TEXT_BUILDERS = {
    "Meeting": meeting_text,
    "Task": task_text,
    "Decision": decision_text,
    "Workgroup": workgroup_text,
}


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #


def embedding_model_name() -> str:
    """The configured model, or "" when vector retrieval is switched off."""
    return os.environ.get(ENV_MODEL, "").strip()


def is_local_model(model: str) -> bool:
    """A bare name runs locally; ``provider/model`` goes to LiteLLM.

    ``Snowflake/snowflake-arctic-embed-xs`` is a HuggingFace repo id, not a
    LiteLLM provider string, so a known-local prefix wins over the slash rule.
    """
    return "/" not in model or model.startswith(("Snowflake/", "sentence-transformers/", "BAAI/"))


@lru_cache(maxsize=2)
def _local_embedder(model: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model)


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed a batch. Used by the index builder; blocking on purpose."""
    model = model or embedding_model_name() or DEFAULT_LOCAL_MODEL
    if is_local_model(model):
        vectors = _local_embedder(model).encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]

    import litellm

    response = litellm.embedding(model=model, input=texts)
    return [item["embedding"] for item in response["data"]]


async def embed_query(text: str) -> list[float] | None:
    """Embed one query for search. Returns ``None`` when nothing is configured
    or the provider fails, so callers can fall back to full text instead of
    erroring at the agent."""
    model = embedding_model_name()
    if not model:
        return None
    try:
        vectors = await asyncio.to_thread(embed_texts, [text], model)
    except Exception:  # noqa: BLE001 - a broken provider must degrade, not crash
        return None
    return vectors[0] if vectors else None
