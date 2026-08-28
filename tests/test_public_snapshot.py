"""Guards on the public/private boundary.

These run against the committed snapshot, so they fail in CI if somebody
regenerates it with a private field in scope.
"""

import importlib.util
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "web" / "public" / "data" / "graph.json"

_spec = importlib.util.spec_from_file_location(
    "export_public_snapshot", REPO_ROOT / "scripts" / "export_public_snapshot.py"
)
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# International prefix, or a long unbroken digit run. Deliberately not
# "digits with separators" — that matches every ISO date in the file.
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


def test_person_records_only_carry_allowlisted_shape():
    allowed = {
        "name",
        "workgroups",
        "meetings",
        "tasks",
        "is_volunteer",
        "availability",
        "skills",
        "interests",
    }
    for person in snapshot()["people"]:
        assert set(person) <= allowed


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
