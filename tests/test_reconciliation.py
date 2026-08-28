"""Removing things from the notes must remove them from the graph.

Recurrence is well covered elsewhere: a task repeated across meetings stays one
task and its status moves. The other half of incremental processing is deletion,
and that is the half worth proving, because reconciliation is most of the reason
this project uses CocoIndex at all. If a task deleted from the document lingers
in Neo4j, the open-work list is wrong and nothing says so.

These tests drive the real pipeline against a temporary notes directory. Neo4j
Community has one database and the app writes the same labels whatever notes it
reads, so there is no way to run a second graph alongside the fixture one: these
tests take the database, wipe it before each case, and rebuild the fixture graph
when the module finishes.

`cocoindex drop` is not used for the cleanup. It reports success and reverts its
own state, but the Neo4j nodes survive it, so the reset here is explicit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from neo4j import GraphDatabase

from neo4j_support import requires_neo4j

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = requires_neo4j

TWO_TASKS = """\
Meeting: 2026-05-01 | Reconciliation fixture

Facilitator: Meera Raghavan
Attendees: Devika Nair

Action items

Task: Keep this one
ID: recon-keep
Workgroup: Program & CFP
Owner: Devika Nair
Status: open

Task: Delete this one
ID: recon-drop
Workgroup: Program & CFP
Owner: Devika Nair
Status: open
"""

ONE_TASK = "\n".join(TWO_TASKS.splitlines()[:-7]) + "\n"


class Pipeline:
    """Runs the real app against a throwaway notes directory and database."""

    def __init__(self, tmp_path: Path) -> None:
        self.notes = tmp_path / "notes"
        self.notes.mkdir()
        self.state = tmp_path / "cocoindex.db"
        self.database = "neo4j"

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT / "src"),
            "MEETING_NOTES_SOURCE": "local",
            "MEETING_NOTES_DIR": str(self.notes),
            "MEETING_EXTRACTOR": "markdown",
            "PERSON_RESOLUTION": "exact",
            # The volunteer fixture would drag unrelated people into the graph.
            "VOLUNTEER_SOURCE": "none",
            "COCOINDEX_DB": str(self.state),
            "WORKGROUPS_CONFIG": str(REPO_ROOT / "config" / "workgroups.yaml"),
        }

    def write(self, name: str, text: str) -> None:
        (self.notes / name).write_text(textwrap.dedent(text), encoding="utf-8")

    def remove(self, name: str) -> None:
        (self.notes / name).unlink()

    def update(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "cocoindex.cli", "-d", "src", "update", "scipy_india_kg.main"],
            cwd=REPO_ROOT,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=300,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0 and "⚠️ errors" not in combined, combined[-2000:]


def wipe_graph() -> None:
    query("MATCH (n) DETACH DELETE n")


@pytest.fixture(scope="module", autouse=True)
def restore_fixture_graph():
    """Give the database back the way it was found.

    The project's own CocoIndex state has to go with the wipe. Emptying Neo4j
    behind CocoIndex's back leaves it believing every node it declared is still
    there, so the next update declares nothing and the graph stays empty. That
    also produced an empty snapshot over the committed one, which is why this
    checks its work rather than trusting the exit code.
    """
    yield
    wipe_graph()
    shutil.rmtree(REPO_ROOT / "cocoindex.db", ignore_errors=True)
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "refresh.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=900,
        check=False,
    )
    restored = meeting_count()
    assert restored > 0, (
        "the fixture graph was not restored after the reconciliation tests.\n"
        f"refresh.sh exited {result.returncode}:\n{result.stdout.decode()[-2000:]}"
    )


@pytest.fixture
def pipeline(tmp_path):
    """An empty graph and a pipeline with its own state pointed at scratch notes."""
    wipe_graph()
    yield Pipeline(tmp_path)


def query(statement: str, **params):
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "scipyindia"),
        ),
    )
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            return [record.data() for record in session.run(statement, **params)]
    finally:
        driver.close()


def descriptions() -> set[str]:
    return {row["d"] for row in query("MATCH (t:Task) RETURN t.description AS d")}


def meeting_count() -> int:
    return query("MATCH (m:Meeting) RETURN count(m) AS c")[0]["c"]


def test_a_task_removed_from_the_notes_leaves_the_graph(pipeline):
    pipeline.write("notes.md", TWO_TASKS)
    pipeline.update()
    assert {"Keep this one", "Delete this one"} <= descriptions()

    pipeline.write("notes.md", ONE_TASK)
    pipeline.update()
    remaining = descriptions()
    assert "Keep this one" in remaining
    assert "Delete this one" not in remaining, "a deleted action item stayed in the graph"


def test_its_edges_go_with_it(pipeline):
    """An orphaned ASSIGNED_TO edge would keep the task on somebody's plate."""
    pipeline.write("notes.md", TWO_TASKS)
    pipeline.update()
    pipeline.write("notes.md", ONE_TASK)
    pipeline.update()

    for relation in ("ASSIGNED_TO", "CREATED_ACTION", "TOUCHED_ACTION", "BELONGS_TO"):
        rows = query(
            f"MATCH ()-[r:{relation}]-(t:Task) WHERE t.description = $d RETURN count(r) AS c",
            d="Delete this one",
        )
        assert rows[0]["c"] == 0, f"{relation} survived the task it pointed at"


def test_deleting_the_whole_file_empties_the_graph(pipeline):
    pipeline.write("notes.md", TWO_TASKS)
    pipeline.update()
    assert meeting_count() == 1

    pipeline.remove("notes.md")
    pipeline.write("placeholder.md", "Notes with no meetings in them.\n")
    pipeline.update()
    assert meeting_count() == 0
    assert descriptions() == set()


def test_a_meeting_removed_from_a_multi_meeting_file(pipeline):
    """The common case: the notes doc is trimmed, not deleted."""
    both = TWO_TASKS + textwrap.dedent("""

        Meeting: 2026-05-15 | Second meeting

        Facilitator: Devika Nair

        Action items

        Task: Only in the second meeting
        Workgroup: Communications
        """)
    pipeline.write("notes.md", both)
    pipeline.update()
    assert "Only in the second meeting" in descriptions()
    assert meeting_count() == 2

    pipeline.write("notes.md", TWO_TASKS)
    pipeline.update()
    assert "Only in the second meeting" not in descriptions()
    assert meeting_count() == 1
