"""Collapsing the same person written several ways into one ``Person`` node.

Two strategies:

``exact``
    Normalise case, punctuation and whitespace, then group. "Meera Raghavan",
    "meera raghavan" and "Meera  Raghavan" become one person; "Meera R." does
    not. No models, no network, fully deterministic: the right default for the
    fixture demo and for CI.

``embedding``
    CocoIndex's ``resolve_entities``: embed every raw name, shortlist by vector
    distance, and ask the LLM to confirm only the close pairs. This is the
    upstream example's behaviour and what you want on real notes, where the same
    person genuinely does appear as "Meera", "Meera Raghavan" and "meera r".

Both return CocoIndex's ``ResolvedEntities``, so the pipeline treats them alike.
"""

from __future__ import annotations

import re

from cocoindex.ops.entity_resolution import ResolvedEntities

_WHITESPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize_name(name: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCT.sub("", name).lower()).strip()


def _canonical_rank(name: str) -> tuple[int, int, int, str]:
    """Rank spellings so the tidiest one becomes the node's name: no stray
    whitespace first, then properly capitalised, then longer, then alphabetical
    so a run is always reproducible."""
    stray_whitespace = len(name) - len(_WHITESPACE.sub(" ", name.strip()))
    return (stray_whitespace, -sum(c.isupper() for c in name), -len(name), name)


def resolve_exact(names: set[str]) -> ResolvedEntities:
    """Group names by normalised form and pick the tidiest spelling as canonical."""
    groups: dict[str, list[str]] = {}
    for name in names:
        key = normalize_name(name)
        if key:
            groups.setdefault(key, []).append(name)

    dedup: dict[str, str | None] = {}
    for variants in groups.values():
        canonical = sorted(variants, key=_canonical_rank)[0]
        dedup[canonical] = None
        for variant in variants:
            if variant != canonical:
                dedup[variant] = canonical
    return ResolvedEntities(dedup)


async def resolve_embedding(names: set[str], embedder, model: str) -> ResolvedEntities:
    """Embedding shortlist plus an LLM confirmation on close pairs."""
    from cocoindex.ops.entity_resolution import resolve_entities
    from cocoindex.ops.entity_resolution.llm_resolver import LlmPairResolver

    return await resolve_entities(
        entities=names,
        embedder=embedder,
        resolve_pair=LlmPairResolver(model=model),
    )
