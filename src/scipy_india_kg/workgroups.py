"""Workgroup registry.

Workgroups come from a YAML file, never from code. The registry also does the
one piece of normalisation the rest of the pipeline needs: turning whatever a
meeting note or form response calls a workgroup ("Design", "design & branding",
"Creatives") into a stable slug.

Text that doesn't match any registered workgroup or alias resolves to ``None``.
The pipeline drops it rather than guessing, so an unregistered work area shows
up as a gap in the graph instead of a wrong edge.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = "./config/workgroups.yaml"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_key(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    ``Design & Branding`` becomes ``design branding``.
    """
    return _NON_ALNUM.sub(" ", text.strip().lower()).strip()


@dataclass(frozen=True)
class Workgroup:
    slug: str
    name: str
    description: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


class WorkgroupRegistry:
    """Immutable lookup over the configured workgroups."""

    def __init__(self, workgroups: list[Workgroup]) -> None:
        self._workgroups = list(workgroups)
        self._by_slug = {w.slug: w for w in workgroups}
        self._index: dict[str, str] = {}
        for w in workgroups:
            for candidate in (w.slug, w.name, *w.aliases):
                self._index[normalize_key(candidate)] = w.slug

    def __len__(self) -> int:
        return len(self._workgroups)

    def __iter__(self):
        return iter(self._workgroups)

    @property
    def slugs(self) -> list[str]:
        return [w.slug for w in self._workgroups]

    def get(self, slug: str) -> Workgroup | None:
        return self._by_slug.get(slug)

    def resolve_exact(self, text: str | None) -> str | None:
        """Map text to a slug only when it names a workgroup and nothing else.

        ``resolve`` finds a registered name inside a longer phrase, which is what
        you want for "sponsorship follow-ups" and exactly what you do not want
        when deciding where a workgroup name ends in a run-together line: the
        whole tail of "joins Sponsoring Srihari Thyagarajan joins Registration &
        Help Desk" contains a longer registered name than the one it starts with.
        """
        if not text:
            return None
        return self._index.get(normalize_key(text))

    def resolve(self, text: str | None) -> str | None:
        """Map free text to a workgroup slug, or ``None`` if nothing matches."""
        if not text:
            return None
        key = normalize_key(text)
        if not key:
            return None
        if key in self._index:
            return self._index[key]
        # Allow a registered name to be found inside a longer phrase, e.g.
        # "sponsorship follow-ups" -> sponsorship. Longest match wins so
        # "design" doesn't beat "design branding".
        best: tuple[int, str] | None = None
        for indexed, slug in self._index.items():
            if len(indexed) < 4:
                continue
            if re.search(rf"\b{re.escape(indexed)}\b", key):
                if best is None or len(indexed) > best[0]:
                    best = (len(indexed), slug)
        return best[1] if best else None

    def prompt_listing(self) -> str:
        """Renderable list of workgroups, injected into the LLM extraction prompt."""
        return "\n".join(f"- {w.slug}: {w.name}. {w.description}" for w in self._workgroups)


def load_registry(path: str | Path | None = None) -> WorkgroupRegistry:
    config_path = Path(path or os.environ.get("WORKGROUPS_CONFIG", DEFAULT_CONFIG_PATH))
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = raw.get("workgroups") or []
    workgroups = [
        Workgroup(
            slug=str(e["slug"]),
            name=str(e.get("name", e["slug"])),
            description=str(e.get("description", "")),
            aliases=tuple(str(a) for a in (e.get("aliases") or [])),
        )
        for e in entries
    ]
    if not workgroups:
        raise ValueError(f"No workgroups defined in {config_path}")
    return WorkgroupRegistry(workgroups)


@lru_cache(maxsize=8)
def _cached_registry(resolved_path: str) -> WorkgroupRegistry:
    return load_registry(resolved_path)


def default_registry() -> WorkgroupRegistry:
    path = os.environ.get("WORKGROUPS_CONFIG", DEFAULT_CONFIG_PATH)
    return _cached_registry(str(Path(path).resolve()))
