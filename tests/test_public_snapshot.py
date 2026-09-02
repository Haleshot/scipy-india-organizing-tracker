"""Guards on the public/private boundary.

These run against the committed snapshot, so they fail in CI if somebody
regenerates it with a private field in scope.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "web" / "public" / "data" / "graph.json"

_spec = importlib.util.spec_from_file_location(
    "export_public_snapshot", REPO_ROOT / "scripts" / "export_public_snapshot.py"
)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# International prefix, or a long unbroken digit run. Deliberately not
# "digits with separators", which matches every ISO date in the file.
PHONE_RE = re.compile(r"\+\d[\d\s().-]{7,}\d|\d{10,}")


def snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_snapshot_is_committed():
    assert SNAPSHOT.is_file(), "run scripts/export_public_snapshot.py"


def test_no_contact_details_anywhere():
    text = SNAPSHOT.read_text(encoding="utf-8")
    assert not EMAIL_RE.search(text)
    assert not PHONE_RE.search(text)
    for needle in ("contact_email", "contact_phone", "raw_response"):
        assert needle not in text


def test_no_note_file_paths():
    # note_file is a path into somebody's Drive; it is not in the allowlist.
    assert "note_file" not in SNAPSHOT.read_text(encoding="utf-8")


def test_volunteer_pipeline_is_counts_by_default():
    for row in snapshot()["volunteer_pipeline"]:
        assert set(row) == {"workgroup", "awaiting_assignment"}


def test_declined_applicants_are_not_named():
    data = snapshot()
    names = {p["name"] for p in data["people"]}
    # Vikram Chandrasekaran's fixture application is declined and he has no
    # graph role, so he must not appear anywhere in the public snapshot.
    assert "Vikram Chandrasekaran" not in names
    assert "Vikram" not in SNAPSHOT.read_text(encoding="utf-8")


def test_the_committed_snapshot_is_the_public_profile():
    """The organizer export carries volunteer availability and skills. Only the
    public one is safe to deploy, so only the public one is committed."""
    assert snapshot()["profile"] == "public"


def test_public_people_carry_nothing_from_a_volunteer_application():
    """A public reader learns what someone did in the open, not what they wrote
    on a form. This is the whole difference between the two profiles."""
    allowed = {"name", "workgroups", "meetings", "tasks"}
    for person in snapshot()["people"]:
        assert set(person) <= allowed, f"{person['name']} carries {set(person) - allowed}"


def test_no_application_derived_field_names_appear_at_all():
    text = SNAPSHOT.read_text(encoding="utf-8")
    for field in ("availability", "skills", "interests", "is_volunteer", "raw_response"):
        assert f'"{field}"' not in text


def test_audit_catches_a_leak():
    assert export.audit({"people": [{"contact_email": "x@y.z"}]})
    assert export.audit({"ok": [{"name": "Devika Nair"}]}) == []


def test_graph_edges_only_reference_known_nodes():
    graph = snapshot()["graph"]
    ids = {node["id"] for node in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in ids and edge["target"] in ids


def test_summary_matches_the_lists():
    data = snapshot()
    assert data["summary"]["meetings"] == len(data["meetings"])
    assert data["summary"]["tasks"] == len(data["tasks"])
    assert data["summary"]["workgroups"] == len(data["workgroups"])
    assert data["summary"]["people_listed"] == len(data["people"])


def test_the_snapshot_says_how_many_people_it_withheld():
    """The public count is smaller than the graph's, and the page must not
    pretend otherwise."""
    summary = snapshot()["summary"]
    assert summary["people_withheld"] > 0, "the fixture has applicants who are not published"
    assert "people" not in summary, "the ambiguous key was replaced on purpose"


def test_the_snapshot_records_where_it_came_from_without_leaking_how():
    source = snapshot()["source"]
    assert source["notes_source"] in {"local", "google_drive", "unknown"}
    assert source["extraction_mode"] in {"markdown", "llm", "unknown"}
    # Mode names only: no paths, no folder ids, no credentials.
    for value in source.values():
        assert "/" not in value or value.endswith("Z")


def test_task_history_is_chronological_and_matches_the_count():
    for task in snapshot()["tasks"]:
        dates = [entry["date"] for entry in task["history"]]
        assert dates == sorted(dates)
        assert task["meeting_count"] == len({entry["id"] for entry in task["history"]})


def test_tasks_are_keyed_by_id_not_description():
    tasks = snapshot()["tasks"]
    ids = [task["id"] for task in tasks]
    assert len(ids) == len(set(ids))
    descriptions = [task["description"] for task in tasks]
    assert len(descriptions) > len(set(descriptions)), (
        "the fixture is meant to contain two tasks that share a description"
    )


def test_every_task_workgroup_is_a_known_slug():
    data = snapshot()
    slugs = {w["slug"] for w in data["workgroups"]}
    for task in data["tasks"]:
        assert task["workgroup"] is None or task["workgroup"] in slugs


def test_the_two_profiles_differ_only_by_application_fields():
    """Both profiles are built from one allowlist; the profile decides how much
    of it a person record keeps. If they ever diverge further than this, the
    public profile has grown a field nobody reviewed."""
    assert set(export.PROFILES) == {"public", "organizer"}
    assert export.DEFAULT_PROFILE == "public"
    assert set(export.APPLICATION_DERIVED) == {
        "availability",
        "skills",
        "interests",
        "is_volunteer",
    }


def test_the_organizer_export_lands_outside_the_deployable_directory():
    """`web/public` is what GitHub Pages serves. The organizer snapshot must not
    be able to end up there by default."""
    assert "web" not in export.ORGANIZER_OUTPUT.parts
    assert export.ORGANIZER_OUTPUT.parts[-2] == "private"
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "private/" in ignored


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #


def test_no_tracked_file_contains_a_private_key():
    """A key downloaded from Google is named after the project, which no generic
    gitignore pattern catches. This checks the outcome rather than the pattern."""
    import subprocess

    listing = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if listing.returncode != 0:
        pytest.skip("not a git checkout")

    # Assembled rather than written out, so this file does not match itself.
    markers = ("BEGIN " + "PRIVATE KEY", '"private' + '_key"')
    here = Path(__file__).resolve()

    offenders = []
    for name in listing.stdout.split():
        path = REPO_ROOT / name
        if not path.is_file() or path.resolve() == here or path.stat().st_size > 2_000_000:
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(marker in body for marker in markers):
            offenders.append(name)

    assert not offenders, f"tracked files look like they contain a private key: {offenders}"


def test_the_secrets_directory_is_ignored():
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "secrets/" in ignored
