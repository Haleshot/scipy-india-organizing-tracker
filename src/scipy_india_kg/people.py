"""The organising team, loaded from ``config/people.yaml``.

The pipeline learns about people from whatever it reads: a name in a meeting
note, a GitHub login on an issue. Those are different strings for the same
person, and no amount of embedding similarity will tell you that "Haleshot" and
"Srihari Thyagarajan" are one human. So the mapping is written down.

Everyone in this file gets a Person node whether or not they show up anywhere
else, which is deliberate: an organiser with nothing assigned is worth seeing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path("config/people.yaml")


@dataclass(frozen=True)
class TeamMember:
    name: str
    github: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


class PeopleRegistry:
    """Canonical names, and the aliases that resolve to them."""

    def __init__(self, members: list[TeamMember]) -> None:
        self._members = members
        self._by_alias: dict[str, str] = {}
        for member in members:
            for alias in (member.name, member.github, *member.aliases):
                if alias:
                    self._by_alias[alias.strip().casefold()] = member.name

    def __iter__(self):
        return iter(self._members)

    def __len__(self) -> int:
        return len(self._members)

    def resolve(self, name: str) -> str | None:
        """Canonical name for a spelling, or None when nobody claims it.

        None is not a failure. Someone can turn up in the notes without being on
        the organising team, and the ordinary person resolution handles them.
        """
        return self._by_alias.get(name.strip().casefold())

    def names(self) -> list[str]:
        return [member.name for member in self._members]

    def github_logins(self) -> dict[str, str]:
        """login (lowercased) -> canonical name, for people who have one."""
        return {m.github.casefold(): m.name for m in self._members if m.github}


def load_people(path: Path | None = None) -> PeopleRegistry:
    if path is None:
        path = Path(os.environ.get("PEOPLE_CONFIG", str(DEFAULT_CONFIG)))
    if not path.is_file():
        # Optional on purpose. Without it the pipeline still works; it just has
        # no way to connect a GitHub login to a name.
        return PeopleRegistry([])

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("people") or []
    if not isinstance(entries, list):
        raise ValueError(f"{path}: 'people' must be a list.")

    members: list[TeamMember] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("name"):
            raise ValueError(f"{path}: entry {index} needs a 'name'.")
        name = str(entry["name"]).strip()
        if name.casefold() in seen:
            raise ValueError(f"{path}: {name!r} is listed twice.")
        seen.add(name.casefold())
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError(f"{path}: aliases for {name!r} must be a list.")
        members.append(
            TeamMember(
                name=name,
                github=str(entry.get("github") or "").strip(),
                aliases=tuple(str(a).strip() for a in aliases if str(a).strip()),
            )
        )
    return PeopleRegistry(members)
