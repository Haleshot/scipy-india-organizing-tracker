#!/usr/bin/env python3
"""Export a sanitized public snapshot of the graph for the static dashboard.

    private sources -> CocoIndex -> Neo4j -> [this script] -> web/public/data/graph.json

The boundary this script draws is allowlist-based, not blacklist-based. Every
node type has an explicit tuple of public fields in PUBLIC_FIELDS below, and the
Cypher queries return those fields and nothing else. Adding a private field to
the graph therefore cannot leak: it is excluded until somebody adds its name to
this file on purpose.

What is deliberately not exported:

* contact_email, contact_phone, raw_response on VolunteerApplication;
* note_file, which is a path into somebody's Drive;
* the names of people who applied but have not been assigned to a workgroup.
  The public site gets counts, not a roster of pending applicants. Pass
  --include-applicant-names to override, and only do that if the form said the
  answers would be public.

Nothing in this file reads credentials or the environment beyond NEO4J_*.

    python scripts/export_public_snapshot.py
    python scripts/export_public_snapshot.py -o /tmp/graph.json --check
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "web" / "public" / "data" / "graph.json"
# Gitignored. Deliberately not under web/, so it cannot be deployed by accident.
ORGANIZER_OUTPUT = REPO_ROOT / "private" / "organizer-graph.json"

# ---------------------------------------------------------------------------
# The allowlist. This is the whole privacy mechanism; keep it short and obvious.
# ---------------------------------------------------------------------------

# Two profiles, because "sanitized" means different things to a public web page
# and to the organizing team.
#
#   public     goes to GitHub Pages. Nothing that originated in a volunteer
#              application reaches it: no availability, no skills, no interests,
#              and no names of people who applied but have not been assigned.
#              A person appears only through work they did in the open.
#   organizer  the same graph plus the application-derived fields, for a team
#              that already has access to the applications themselves. It is
#              gitignored and the Pages workflow refuses it.
#
# Fixture data makes the difference look harmless. Real applications are the
# reason the default is `public`.
PROFILES = ("public", "organizer")
DEFAULT_PROFILE = "public"

# Fields that exist only because somebody filled in a volunteer form. They are
# the entire difference between the two profiles.
APPLICATION_DERIVED = ("availability", "skills", "interests", "is_volunteer")

PUBLIC_FIELDS: dict[str, tuple[str, ...]] = {
    "Workgroup": ("slug", "name", "description"),
    "Meeting": ("id", "date", "title", "summary", "topics"),
    "Person": ("name",),
    "Task": ("id", "description", "status", "due", "first_seen", "last_seen", "meeting_count"),
    "Decision": ("statement",),
    # How the graph was built. Mode names only, so the dashboard can say whether
    # it is showing fixtures or the real Drive folder. Never a path, a folder id
    # or a credential; the pipeline does not put those on this node either.
    "GraphBuild": ("built_at", "notes_source", "extraction_mode", "person_resolution"),
    # VolunteerApplication contributes aggregate counts always, and the
    # application-derived fields only under the organizer profile. Never contact
    # details, never raw answers, under either.
    "VolunteerApplication": ("status", "availability", "interests", "skills"),
}

# Fields that must never appear anywhere in the output, checked after the fact
# as a belt-and-braces assertion. The allowlist is what actually protects them.
FORBIDDEN_SUBSTRINGS = ("contact_email", "contact_phone", "raw_response")

# A bare "@" used to stand in for "an email address", which was a fine proxy
# while every string in the snapshot came from meeting notes. GitHub issue
# titles broke it: "FOSS in Science devroom @ IndiaFOSS" is not a leak. This
# wants an actual address, and still catches every real one.
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

OPEN_STATUSES = ("open", "in_progress", "blocked", "unknown")


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _iso(value: Any) -> Any:
    if hasattr(value, "iso_format"):  # neo4j.time.Date
        return value.iso_format()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _iso(value) for key, value in row.items()}


# ---------------------------------------------------------------------------
# Queries. Each returns only fields named in PUBLIC_FIELDS.
# ---------------------------------------------------------------------------

Q_WORKGROUPS = """
MATCH (w:Workgroup)
RETURN w.slug AS slug, w.name AS name, w.description AS description
ORDER BY name
"""

Q_MEETINGS = """
MATCH (m:Meeting)
OPTIONAL MATCH (p:Person)-[r:ATTENDED]->(m)
OPTIONAL MATCH (m)-[:DISCUSSED]->(w:Workgroup)
RETURN m.id AS id, m.date AS date, m.title AS title, m.summary AS summary,
       m.topics AS topics,
       [x IN collect(DISTINCT CASE WHEN r.is_organizer THEN p.name END)
         WHERE x IS NOT NULL][0] AS facilitator,
       [x IN collect(DISTINCT p.name) WHERE x IS NOT NULL] AS attendees,
       [x IN collect(DISTINCT w.slug) WHERE x IS NOT NULL] AS workgroups
ORDER BY date DESC
"""

# Tasks now carry their whole appearance history. `meetings` is every meeting
# that touched the item, oldest first, each with the status it held at the time;
# `created_in` is the one that first recorded it. The dashboard renders that as
# "Seen in N meetings" rather than a bare list of dates.
Q_TASKS = """
MATCH (t:Task)
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
OPTIONAL MATCH (creator:Meeting)-[:CREATED_ACTION]->(t)
WITH t, w, creator, [x IN collect(DISTINCT owner.name) WHERE x IS NOT NULL] AS owners
RETURN t.id AS id, t.description AS description, t.status AS status, t.due AS due,
       t.first_seen AS first_seen, t.last_seen AS last_seen,
       t.meeting_count AS meeting_count,
       w.slug AS workgroup, owners,
       creator.id AS created_in,
       [entry IN COLLECT {
           MATCH (m:Meeting)-[touch:TOUCHED_ACTION]->(t)
           RETURN {id: m.id, date: toString(touch.date), status: touch.status}
           ORDER BY touch.date
       } | entry] AS history
ORDER BY status, description
"""

Q_DECISIONS = """
MATCH (m:Meeting)-[:DECIDED]->(d:Decision)
OPTIONAL MATCH (d)-[:CONCERNS]->(w:Workgroup)
RETURN d.statement AS statement, w.slug AS workgroup,
       collect(DISTINCT m.id) AS meetings,
       max(m.date) AS date
ORDER BY date DESC, statement
"""

# People with a role in the graph: they ran or attended a meeting, own a task,
# or are a member of a workgroup. Someone who only ever submitted an
# application does not appear here.
Q_PEOPLE = """
MATCH (p:Person)
WHERE (p)-[:ATTENDED]->(:Meeting)
   OR (p)-[:ASSIGNED_TO]->(:Task)
   OR (p)-[:MEMBER_OF]->(:Workgroup)
OPTIONAL MATCH (p)-[:MEMBER_OF]->(w:Workgroup)
OPTIONAL MATCH (p)-[:ATTENDED]->(m:Meeting)
OPTIONAL MATCH (p)-[:ASSIGNED_TO]->(t:Task)
RETURN p.name AS name,
       [x IN collect(DISTINCT w.slug) WHERE x IS NOT NULL] AS workgroups,
       [x IN collect(DISTINCT m.id) WHERE x IS NOT NULL] AS meetings,
       [x IN collect(DISTINCT t.id) WHERE x IS NOT NULL] AS tasks
ORDER BY name
"""

Q_BUILD = """
MATCH (b:GraphBuild {id: 'singleton'})
RETURN toString(b.built_at) AS built_at, b.notes_source AS notes_source,
       b.extraction_mode AS extraction_mode, b.person_resolution AS person_resolution
"""

# GitHub issues. Everything here is already public on github.com, which is why
# it needs no allowlisting the way the volunteer tables do.
Q_ISSUES = """
MATCH (i:Issue)
OPTIONAL MATCH (i)-[:FILED_UNDER]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:WORKS_ON]->(i)
OPTIONAL MATCH (t:Task)-[:TRACKED_BY]->(i)
RETURN i.key AS key,
       i.repo AS repo,
       i.number AS number,
       i.title AS title,
       i.url AS url,
       i.state AS state,
       i.state_reason AS state_reason,
       i.labels AS labels,
       i.milestone AS milestone,
       i.comment_count AS comment_count,
       i.updated_at AS updated_at,
       w.slug AS workgroup,
       [x IN collect(DISTINCT owner.name) WHERE x IS NOT NULL] AS owners,
       [x IN collect(DISTINCT t.id) WHERE x IS NOT NULL] AS tasks
ORDER BY i.number DESC
"""

Q_TOTAL_PEOPLE = "MATCH (p:Person) RETURN count(p) AS count"

# Skills and availability of people who are already on a workgroup. Their
# involvement is public; the free-text answers behind it are not.
Q_ASSIGNED_VOLUNTEERS = """
MATCH (p:Person)-[:SUBMITTED]->(a:VolunteerApplication)
WHERE (p)-[:MEMBER_OF]->(:Workgroup)
RETURN p.name AS name, a.status AS status, a.availability AS availability,
       a.interests AS interests, a.skills AS skills
ORDER BY name
"""

# Pending interest, aggregated. No names.
Q_PIPELINE = """
MATCH (p:Person)-[:INTERESTED_IN]->(w:Workgroup)
MATCH (p)-[:SUBMITTED]->(a:VolunteerApplication)
WHERE NOT (p)-[:MEMBER_OF]->(w) AND a.status <> 'declined' AND a.status <> 'withdrawn'
RETURN w.slug AS workgroup, count(DISTINCT p) AS awaiting_assignment
ORDER BY workgroup
"""

Q_PIPELINE_NAMED = """
MATCH (p:Person)-[:INTERESTED_IN]->(w:Workgroup)
MATCH (p)-[:SUBMITTED]->(a:VolunteerApplication)
WHERE NOT (p)-[:MEMBER_OF]->(w) AND a.status <> 'declined' AND a.status <> 'withdrawn'
RETURN w.slug AS workgroup, collect(DISTINCT p.name) AS people,
       count(DISTINCT p) AS awaiting_assignment
ORDER BY workgroup
"""

Q_APPLICATION_COUNTS = """
MATCH (a:VolunteerApplication)
RETURN a.status AS status, count(*) AS count
ORDER BY status
"""


def build_snapshot(
    session, *, profile: str = DEFAULT_PROFILE, include_applicant_names: bool = False
) -> dict[str, Any]:
    def rows(query: str) -> list[dict[str, Any]]:
        return [_clean(record.data()) for record in session.run(query)]

    workgroups = rows(Q_WORKGROUPS)
    meetings = rows(Q_MEETINGS)
    tasks = rows(Q_TASKS)
    decisions = rows(Q_DECISIONS)
    people = rows(Q_PEOPLE)
    issues = rows(Q_ISSUES)
    volunteers = rows(Q_ASSIGNED_VOLUNTEERS)
    build_rows = rows(Q_BUILD)
    total_people = rows(Q_TOTAL_PEOPLE)
    pipeline = rows(Q_PIPELINE_NAMED if include_applicant_names else Q_PIPELINE)
    application_counts = rows(Q_APPLICATION_COUNTS)

    if profile == "organizer":
        volunteer_by_name = {v["name"]: v for v in volunteers}
        for person in people:
            detail = volunteer_by_name.get(person["name"])
            person["is_volunteer"] = detail is not None
            person["availability"] = detail["availability"] if detail else ""
            person["skills"] = detail["skills"] if detail else []
            person["interests"] = detail["interests"] if detail else []
    else:
        # A public reader learns that somebody ran a meeting and owns three
        # action items. They do not learn when that person said they were free.
        for person in people:
            for field in APPLICATION_DERIVED:
                person.pop(field, None)

    open_tasks = [t for t in tasks if t["status"] in OPEN_STATUSES]
    by_workgroup = {w["slug"]: {"open": 0, "total": 0, "people": 0} for w in workgroups}
    for task in tasks:
        slug = task["workgroup"]
        if slug in by_workgroup:
            by_workgroup[slug]["total"] += 1
            if task["status"] in OPEN_STATUSES:
                by_workgroup[slug]["open"] += 1
    for person in people:
        for slug in person["workgroups"]:
            if slug in by_workgroup:
                by_workgroup[slug]["people"] += 1
    awaiting = {row["workgroup"]: row["awaiting_assignment"] for row in pipeline}
    for workgroup in workgroups:
        stats = by_workgroup[workgroup["slug"]]
        workgroup["open_tasks"] = stats["open"]
        workgroup["total_tasks"] = stats["total"]
        workgroup["member_count"] = stats["people"]
        workgroup["awaiting_assignment"] = awaiting.get(workgroup["slug"], 0)

    # The private graph holds more people than this: pending applicants are
    # counted, not named. The dashboard says "people listed here" rather than
    # "people in the graph" because those are two different numbers, and the
    # gap between them is the whole point of the export boundary.
    named = len(people)
    withheld = max(0, (total_people[0]["count"] if total_people else named) - named)

    source = build_rows[0] if build_rows else {}

    return {
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "schema_version": 4,
        "profile": profile,
        "source": {
            "built_at": source.get("built_at", ""),
            "notes_source": source.get("notes_source", "unknown"),
            "extraction_mode": source.get("extraction_mode", "unknown"),
            "person_resolution": source.get("person_resolution", "unknown"),
        },
        "summary": {
            "meetings": len(meetings),
            "people_listed": named,
            "people_withheld": withheld,
            "tasks": len(tasks),
            "open_tasks": len(open_tasks),
            "unassigned_open_tasks": sum(1 for t in open_tasks if not t["owners"]),
            "decisions": len(decisions),
            "workgroups": len(workgroups),
            "issues": len(issues),
            "open_issues": sum(1 for i in issues if i["state"] == "open"),
            "applications_by_status": {r["status"]: r["count"] for r in application_counts},
        },
        "workgroups": workgroups,
        "meetings": meetings,
        "people": people,
        "tasks": tasks,
        "decisions": decisions,
        "issues": issues,
        "volunteer_pipeline": pipeline,
        "graph": build_graph_view(workgroups, meetings, people, tasks, decisions, issues),
    }


def build_graph_view(workgroups, meetings, people, tasks, decisions, issues) -> dict[str, Any]:
    """Node/edge lists for the explorer. Ids are typed so the UI can style them."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_node(node_id: str, label: str, kind: str) -> str:
        if node_id not in seen:
            seen.add(node_id)
            nodes.append({"id": node_id, "label": label, "kind": kind})
        return node_id

    def add_edge(source: str, target: str, kind: str) -> None:
        edges.append({"source": source, "target": target, "kind": kind})

    for workgroup in workgroups:
        add_node(f"workgroup:{workgroup['slug']}", workgroup["name"], "workgroup")
    for meeting in meetings:
        add_node(f"meeting:{meeting['id']}", f"{meeting['date']} {meeting['title']}", "meeting")
        for slug in meeting["workgroups"]:
            add_edge(f"meeting:{meeting['id']}", f"workgroup:{slug}", "DISCUSSED")
    for person in people:
        node = add_node(f"person:{person['name']}", person["name"], "person")
        for slug in person["workgroups"]:
            add_edge(node, f"workgroup:{slug}", "MEMBER_OF")
        for meeting_id in person["meetings"]:
            add_edge(node, f"meeting:{meeting_id}", "ATTENDED")
    for task in tasks:
        node = add_node(f"task:{task['id']}", task["description"], "task")
        if task["workgroup"]:
            add_edge(node, f"workgroup:{task['workgroup']}", "BELONGS_TO")
        for owner in task["owners"]:
            add_edge(f"person:{owner}", node, "ASSIGNED_TO")
        if task["created_in"] is not None:
            add_edge(f"meeting:{task['created_in']}", node, "CREATED_ACTION")
        for entry in task["history"]:
            if entry["id"] != task["created_in"]:
                add_edge(f"meeting:{entry['id']}", node, "TOUCHED_ACTION")
    for decision in decisions:
        node = add_node(f"decision:{decision['statement']}", decision["statement"], "decision")
        if decision["workgroup"]:
            add_edge(node, f"workgroup:{decision['workgroup']}", "CONCERNS")
        for meeting_id in decision["meetings"]:
            add_edge(f"meeting:{meeting_id}", node, "DECIDED")

    # Issues, and the two places they touch the rest of the graph: a person
    # GitHub says is on it, and a task a note explicitly tied to it.
    for issue in issues:
        node = add_node(f"issue:{issue['key']}", f"#{issue['number']} {issue['title']}", "issue")
        if issue["workgroup"]:
            add_edge(node, f"workgroup:{issue['workgroup']}", "FILED_UNDER")
        for owner in issue["owners"]:
            add_edge(f"person:{owner}", node, "WORKS_ON")
        for task_id in issue["tasks"]:
            add_edge(f"task:{task_id}", node, "TRACKED_BY")

    known = {node["id"] for node in nodes}
    edges = [e for e in edges if e["source"] in known and e["target"] in known]
    return {"nodes": nodes, "edges": edges}


def audit(payload: dict[str, Any]) -> list[str]:
    """Cheap post-hoc check that nothing private slipped through. The allowlist
    is the real defence; this catches a mistake in it."""
    text = json.dumps(payload)
    found = [needle for needle in FORBIDDEN_SUBSTRINGS if needle in text]
    found.extend(sorted(set(EMAIL_RE.findall(text))))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help=(
            "public (default) excludes everything derived from volunteer applications "
            "and is the only profile the Pages workflow accepts; organizer includes "
            "availability, skills and interests and is gitignored."
        ),
    )
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument(
        "--include-applicant-names",
        action="store_true",
        help="publish the names of people awaiting assignment (needs their consent)",
    )
    parser.add_argument("--check", action="store_true", help="fail if the output would change")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    output = args.output or (DEFAULT_OUTPUT if args.profile == "public" else ORGANIZER_OUTPUT)
    # Imported here rather than at module scope so the allowlist and the audit
    # can be read without the driver installed. tests/test_public_snapshot.py
    # imports this module to check PUBLIC_FIELDS against the committed snapshot
    # and never opens a connection.
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "scipyindia"),
        ),
    )
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as session:
            payload = build_snapshot(
                session,
                profile=args.profile,
                include_applicant_names=args.include_applicant_names,
            )
    finally:
        driver.close()

    leaks = audit(payload)
    if leaks:
        print(f"Refusing to write: snapshot contains {leaks}", file=sys.stderr)
        return 1

    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"

    if args.check:
        if not output.is_file():
            print(f"{output} does not exist", file=sys.stderr)
            return 1
        existing = output.read_text(encoding="utf-8")
        # generated_at always differs; compare everything else.
        if _strip_timestamp(existing) != _strip_timestamp(rendered):
            print(f"{output} is out of date", file=sys.stderr)
            return 1
        print(f"{output} is up to date")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    summary = payload["summary"]
    where = output.relative_to(REPO_ROOT) if output.is_relative_to(REPO_ROOT) else output
    print(
        f"Wrote {where}: "
        f"{summary['meetings']} meetings, {summary['people_listed']} people "
        f"({summary['people_withheld']} withheld), {summary['tasks']} tasks "
        f"({summary['open_tasks']} open, {summary['unassigned_open_tasks']} unassigned), "
        f"{summary['decisions']} decisions, {summary['workgroups']} workgroups."
    )
    return 0


# Two timestamps move on every run without the data changing: when the snapshot
# was exported, and when the pipeline last ran. Comparing them would make
# --check report "stale" immediately after a refresh.
_RUN_TIMESTAMPS = ('"generated_at"', '"built_at"')


def _strip_timestamp(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not any(key in line for key in _RUN_TIMESTAMPS)
    )


if __name__ == "__main__":
    raise SystemExit(main())
