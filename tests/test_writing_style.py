"""A guard on the prose, because promising to be careful has not worked.

Every pass of this project has reintroduced em dashes somewhere, so this checks
rather than trusts. It covers the two things a reader actually sees, the docs
and the dashboard, plus the comments and docstrings a contributor reads.

Deliberately narrow. It is a lint for a house rule, not an AI detector, and it
does not try to judge whether prose is any good.
"""

from __future__ import annotations

import json
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


SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "cocoindex.db",
    "private",
    "vendor",
}
# Mirrors .gitignore. Review artefacts other tools drop in are not ours to lint.
SKIP_GLOBS = ("*_AUDIT.md", "*_SCREENSHOTS/*")


def tracked_files() -> list[Path]:
    """Prefer git, fall back to walking. A source tarball or a copied tree is
    not a git checkout, and this check should still run there."""
    try:
        listing = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return [
            path
            for path in REPO_ROOT.rglob("*")
            if path.is_file()
            and not SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts)
            and not any(path.match(pattern) for pattern in SKIP_GLOBS)
        ]
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
        "SciPy",
        "India",
        "CocoIndex",
        "Neo4j",
        "Google",
        "Docs",
        "Doc",
        "Drive",
        "Claude",
        "Code",
        "Desktop",
        "GitHub",
        "Pages",
        "Cypher",
        "MCP",
        "CLI",
        "LLM",
        "Markdown",
        "NeoCarta",
        "Actions",
        "Python",
        "Docker",
        "Compose",
        "ID",
        "IDs",
        "JSON",
        "YAML",
        "API",
        "The",
        "A",
        "An",
    }
    # Workgroup names are proper nouns in this project, and they turn up in
    # meeting titles.
    known |= {word for name in _workgroup_names() for word in name.replace("&", " ").split()}
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
    """The one a reader sees. Checks the built page and its data together.

    The snapshot carries GitHub issue titles verbatim, and other people punctuate
    how they like. Quoting someone accurately beats house style, so the scan
    covers the strings this project writes and skips the ones it repeats.
    """
    for name in ("index.html", "app.js", "styles.css"):
        text = (REPO_ROOT / "web" / "public" / name).read_text(encoding="utf-8")
        assert not DASHES.search(text), f"em or en dash in web/public/{name}"

    snapshot = json.loads((REPO_ROOT / "web" / "public" / "data" / "graph.json").read_text())
    ours = {key: value for key, value in snapshot.items() if key not in ("issues", "graph")}
    assert not DASHES.search(json.dumps(ours)), "em or en dash in the snapshot"


# --------------------------------------------------------------------------- #
# The dashboard's visual defaults
#
# The same reasoning as the prose checks above. These are the tells that make an
# interface read as generated rather than designed, and every one of them was
# present at some point in this project's history. Checking beats remembering.
#
# Comments are stripped before matching, so a comment explaining why a pattern
# is absent does not trip the check that it is absent.
# --------------------------------------------------------------------------- #

WEB = REPO_ROOT / "web" / "public"

VISUAL_TELLS = (
    ("gradients", r"linear-gradient|radial-gradient|conic-gradient"),
    ("glow shadows", r"box-shadow:[^;]*0 0 \d+px"),
    ("capsule buttons", r"border-radius:\s*(?:999|9999|50)px"),
    ("sparkle or emoji decoration", r"[✨\U0001F300-\U0001FAFF]"),
    ("pulsing status dots", r"@keyframes|animation:\s*\w*(?:pulse|blink)"),
    ("the generic violet palette", r"#7c3aed|#8b5cf6|#a855f7|#be185d|#ec4899"),
    ("auto-fit card grids", r"repeat\(\s*auto-fit"),
    ("opacity hover fades", r"transition:[^;]*opacity"),
)


def _without_comments(text: str, kind: str) -> str:
    if kind == "css":
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", re.sub(r"^\s*//.*$", "", text, flags=re.M), flags=re.S)


@pytest.mark.parametrize("label,pattern", VISUAL_TELLS, ids=[t[0] for t in VISUAL_TELLS])
def test_the_dashboard_avoids_generated_ui_defaults(label, pattern):
    for name, kind in (("styles.css", "css"), ("app.js", "js"), ("index.html", "html")):
        body = _without_comments((WEB / name).read_text(encoding="utf-8"), kind)
        assert not re.search(pattern, body, re.IGNORECASE), f"{label} in web/public/{name}"


def test_spacing_stays_on_the_grid():
    """8px grid, with 4px as the only half step and 2px for optical nudges."""
    css = _without_comments((WEB / "styles.css").read_text(encoding="utf-8"), "css")
    values = [int(v) for v in re.findall(r"(?:padding|margin|gap):\s*(\d+)px", css)]
    assert values, "expected to find spacing declarations"
    off = sorted({v for v in values if v % 4 and v not in (1, 2)})
    assert not off, f"spacing off the grid: {off}"


def test_one_accent_colour_and_it_is_the_logo_blue():
    """A second accent is how a palette drifts. The graph legend is separate: it
    encodes categories, and its colours come from the logo too."""
    css = _without_comments((WEB / "styles.css").read_text(encoding="utf-8"), "css")
    accents = re.findall(r"--accent:\s*(#[0-9a-fA-F]{6})", css)
    assert accents, "no --accent defined"
    assert accents[0].lower() == "#0054a6", "the light accent must be the SciPy logo blue"
    assert len(set(accents)) <= 2, f"more than one accent per scheme: {accents}"
