"""A guard on the prose, because promising to be careful has not worked.

Every pass of this project has reintroduced em dashes somewhere, so this checks
rather than trusts. It covers the two things a reader actually sees, the docs
and the dashboard, plus the comments and docstrings a contributor reads.

Deliberately narrow. It is a lint for a house rule, not an AI detector, and it
does not try to judge whether prose is any good.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

DASHES = re.compile(r"[—–]")

# A dash inside a character class matches somebody else's text, and a dash
# inside a Python string literal that also contains \n is a test building notes
# in the legacy inline format the parser still accepts. Both are data.
ALLOWED = (
    re.compile(r"re\.compile"),
    re.compile(r"\\n"),
    re.compile(r"^\s*\"[-—]"),
)

PROSE_SUFFIXES = (".md", ".py", ".js", ".css", ".html", ".yaml", ".yml", ".sh", ".cypher", ".txt")


def tracked_files() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return [REPO_ROOT / name for name in listing.stdout.split()]


def prose_files() -> list[Path]:
    return [
        path
        for path in tracked_files()
        if path.suffix in PROSE_SUFFIXES and "vendor" not in path.parts and path.is_file()
    ]


def _workgroup_names() -> list[str]:
    import yaml

    config = yaml.safe_load((REPO_ROOT / "config" / "workgroups.yaml").read_text())
    return [entry["name"] for entry in config["workgroups"]]


def test_there_are_files_to_check():
    assert len(prose_files()) > 20


@pytest.mark.parametrize("path", prose_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_em_dashes_in_prose(path: Path):
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()[:90]}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if DASHES.search(line) and not any(pattern.search(line) for pattern in ALLOWED)
    ]
    assert not offenders, "em or en dashes in prose:\n" + "\n".join(offenders)


def test_markdown_headings_are_sentence_case():
    """Title Case In Headings is a house-style tell. Proper nouns and code are
    exempt, so the check is for two or more capitalised ordinary words."""
    known = {
        "SciPy", "India", "CocoIndex", "Neo4j", "Google", "Docs", "Doc", "Drive",
        "Claude", "Code", "Desktop", "GitHub", "Pages", "Cypher", "MCP", "CLI",
        "LLM", "Markdown", "NeoCarta", "Actions", "Python", "Docker", "Compose",
        "ID", "IDs", "JSON", "YAML", "API", "The", "A", "An",
    }
    # Workgroup names are proper nouns in this project, and they turn up in
    # meeting titles.
    known |= {
        word
        for name in _workgroup_names()
        for word in name.replace("&", " ").split()
    }
    offenders = []
    for path in prose_files():
        if path.suffix != ".md":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.startswith("#"):
                continue
            words = re.sub(r"^#+\s*", "", line).split()
            capitalised = [
                word
                for word in words[1:]
                if word[:1].isupper() and word.strip("`*_,.:") not in known
            ]
            if len(capitalised) >= 2:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "headings look title-cased:\n" + "\n".join(offenders)


def test_no_emoji_in_markdown_headings():
    emoji = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}"
        for path in prose_files()
        if path.suffix == ".md"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if line.startswith("#") and emoji.search(line)
    ]
    assert not offenders, "emoji in headings:\n" + "\n".join(offenders)


def test_the_dashboard_ships_no_em_dashes():
    """The one a reader sees. Checks the built page and its data together."""
    for name in ("index.html", "app.js", "styles.css", "data/graph.json"):
        text = (REPO_ROOT / "web" / "public" / name).read_text(encoding="utf-8")
        assert not DASHES.search(text), f"em or en dash in web/public/{name}"
