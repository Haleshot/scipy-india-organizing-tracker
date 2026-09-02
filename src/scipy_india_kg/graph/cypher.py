"""Cypher for the retrieval layer.

Query text lives here and nowhere else, so the MCP server and the CLI cannot
drift apart: both call :class:`~scipy_india_kg.graph.service.OrganizerGraph`,
which is the only caller of these strings. NeoCarta separates its Cypher from
its tools the same way, for the same reason.

Every statement in this module reads. None of them contain CREATE, MERGE, SET or
DELETE, and the service runs them under ``RoutingControl.READ`` so a mistake here
is rejected by the database rather than executed.
"""

from __future__ import annotations

# Statuses that mean "still on the list". "unknown" is included on purpose: the
# notes not saying a task is finished is not evidence that it is.
OPEN_STATUSES = ["open", "in_progress", "blocked", "unknown"]

# Reusable projection of a Meeting node into MeetingSummary shape.
_MEETING_FIELDS = """
    m.id AS id, m.date AS date, m.title AS title, m.summary AS summary,
    m.topics AS topics, m.source_ref AS source_ref,
    head([x IN collect(DISTINCT CASE WHEN att.is_organizer THEN p.name END)
          WHERE x IS NOT NULL]) AS facilitator,
    count(DISTINCT p) AS attendee_count,
    [x IN collect(DISTINCT w.slug) WHERE x IS NOT NULL] AS workgroups,
    count(DISTINCT d) AS decision_count,
    count(DISTINCT t) AS action_item_count
"""

_MEETING_MATCH = """
OPTIONAL MATCH (p:Person)-[att:ATTENDED]->(m)
OPTIONAL MATCH (m)-[:DISCUSSED]->(w:Workgroup)
OPTIONAL MATCH (m)-[:DECIDED]->(d:Decision)
OPTIONAL MATCH (m)-[:TOUCHED_ACTION]->(t:Task)
"""

LIST_RECENT_MEETINGS = f"""
MATCH (m:Meeting)
{_MEETING_MATCH}
WITH {_MEETING_FIELDS}
RETURN * ORDER BY date DESC, id DESC LIMIT $limit
"""

GET_MEETING = f"""
MATCH (m:Meeting)
WHERE ($meeting_id IS NULL OR m.id = $meeting_id)
  AND ($date IS NULL OR toString(m.date) = $date)
{_MEETING_MATCH}
WITH {_MEETING_FIELDS}
RETURN * ORDER BY date DESC, id DESC LIMIT 1
"""

GET_MEETING_ATTENDEES = """
MATCH (p:Person)-[r:ATTENDED]->(m:Meeting {id: $meeting_id})
RETURN p.name AS name, r.is_organizer AS is_organizer
ORDER BY r.is_organizer DESC, name
"""

GET_MEETING_DECISIONS = """
MATCH (m:Meeting {id: $meeting_id})-[:DECIDED]->(d:Decision)
OPTIONAL MATCH (d)-[:CONCERNS]->(w:Workgroup)
RETURN d.statement AS statement, w.slug AS workgroup, w.name AS workgroup_name,
       d.first_seen AS date,
       [(mm:Meeting)-[:DECIDED]->(d) | mm.id] AS meetings
ORDER BY workgroup_name, statement
"""

# Action items touched at one meeting, with the status they carried at the
# previous meeting that touched them. That previous value is what makes
# "what changed" answerable without the caller replaying the whole history.
GET_MEETING_ACTION_ITEMS = """
MATCH (m:Meeting {id: $meeting_id})-[touch:TOUCHED_ACTION]->(t:Task)
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
WITH t, touch, m, w,
     [x IN collect(DISTINCT owner.name) WHERE x IS NOT NULL] AS owners,
     head([(prev:Meeting)-[p:TOUCHED_ACTION]->(t)
           WHERE p.date < touch.date | p.status]) AS any_previous
OPTIONAL MATCH (creator:Meeting)-[:CREATED_ACTION]->(t)
RETURN t.id AS id, t.description AS description, w.name AS workgroup_name,
       touch.status AS status_at_meeting, any_previous AS previous_status,
       creator.id = m.id AS is_new, owners
ORDER BY workgroup_name, description
"""

GET_MEETING_JOINERS = """
MATCH (p:Person)-[r:MEMBER_OF]->(w:Workgroup)
WHERE r.first_meeting_id = $meeting_id
RETURN p.name + ' joined ' + w.name AS entry ORDER BY entry
"""

_TASK_FIELDS = """
    t.id AS id, t.description AS description, t.status AS status, t.due AS due,
    w.slug AS workgroup, w.name AS workgroup_name,
    [x IN collect(DISTINCT owner.name) WHERE x IS NOT NULL] AS owners,
    t.first_seen AS first_seen, t.last_seen AS last_seen,
    t.meeting_count AS meeting_count, t.identity_basis AS identity_basis
"""

LIST_OPEN_TASKS = f"""
MATCH (t:Task) WHERE t.status IN $open_statuses
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
WITH {_TASK_FIELDS}
WHERE ($workgroup IS NULL OR workgroup = $workgroup)
  AND ($owner IS NULL OR $owner IN owners)
RETURN * ORDER BY status, workgroup_name, description LIMIT $limit
"""

LIST_UNASSIGNED_TASKS = f"""
MATCH (t:Task)
WHERE t.status IN $open_statuses AND NOT (:Person)-[:ASSIGNED_TO]->(t)
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
WITH {_TASK_FIELDS}
WHERE ($workgroup IS NULL OR workgroup = $workgroup)
RETURN * ORDER BY workgroup_name, description LIMIT $limit
"""

# Issues. Kept apart from the task queries on purpose: a task is what a meeting
# agreed to do and an issue is what somebody filed, and folding them into one
# result would hide which of the two you are reading.
_ISSUE_FIELDS = """
       i.key AS key, i.repo AS repo, i.number AS number, i.title AS title,
       i.url AS url, i.state AS state, i.state_reason AS state_reason,
       i.labels AS labels, i.milestone AS milestone,
       i.comment_count AS comment_count, i.updated_at AS updated_at,
       w.slug AS workgroup, w.name AS workgroup_name,
       [x IN collect(DISTINCT owner.name) WHERE x IS NOT NULL] AS owners,
       [x IN collect(DISTINCT t.description) WHERE x IS NOT NULL] AS tracks
"""

LIST_ISSUES = f"""
MATCH (i:Issue)
OPTIONAL MATCH (i)-[:FILED_UNDER]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:WORKS_ON]->(i)
OPTIONAL MATCH (t:Task)-[:TRACKED_BY]->(i)
WITH {_ISSUE_FIELDS}
WHERE ($state IS NULL OR state = $state)
  AND ($workgroup IS NULL OR workgroup = $workgroup)
  AND ($owner IS NULL OR $owner IN owners)
  AND (NOT $unassigned_only OR size(owners) = 0)
RETURN * ORDER BY number DESC LIMIT $limit
"""

FIND_ISSUE = f"""
MATCH (i:Issue)
WHERE i.key = $needle
   OR toString(i.number) = replace($needle, '#', '')
   OR toLower(i.title) CONTAINS toLower($needle)
OPTIONAL MATCH (i)-[:FILED_UNDER]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:WORKS_ON]->(i)
OPTIONAL MATCH (t:Task)-[:TRACKED_BY]->(i)
WITH {_ISSUE_FIELDS}
RETURN * ORDER BY number DESC LIMIT $limit
"""

FIND_TASK = f"""
MATCH (t:Task)
WHERE t.id = $needle OR toLower(t.description) CONTAINS toLower($needle)
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
WITH {_TASK_FIELDS}, t
RETURN *, t.note_file AS note_file, t.extraction_mode AS extraction_mode
ORDER BY CASE WHEN id = $needle THEN 0 ELSE 1 END, description LIMIT $limit
"""

GET_TASK_HISTORY = """
MATCH (m:Meeting)-[touch:TOUCHED_ACTION]->(t:Task {id: $task_id})
RETURN m.id AS meeting_id, touch.date AS date, m.title AS title,
       touch.status AS status, touch.due AS due
ORDER BY date, meeting_id
"""

GET_TASK_ORIGIN = f"""
MATCH (m:Meeting)-[:CREATED_ACTION]->(:Task {{id: $task_id}})
{_MEETING_MATCH}
WITH {_MEETING_FIELDS}
RETURN * LIMIT 1
"""

GET_PERSON = """
MATCH (p:Person)
WHERE toLower(p.name) = toLower($name) OR toLower(p.name) CONTAINS toLower($name)
OPTIONAL MATCH (p)-[:SUBMITTED]->(a:VolunteerApplication)
OPTIONAL MATCH (p)-[:MEMBER_OF]->(mw:Workgroup)
OPTIONAL MATCH (p)-[:INTERESTED_IN]->(iw:Workgroup)
OPTIONAL MATCH (p)-[org:ATTENDED]->(:Meeting)
RETURN p.name AS name,
       a IS NOT NULL AS is_volunteer,
       coalesce(a.availability, '') AS availability,
       coalesce(a.skills, []) AS skills,
       coalesce(a.interests, []) AS interests,
       [x IN collect(DISTINCT mw.name) WHERE x IS NOT NULL] AS member_of,
       [x IN collect(DISTINCT iw.name) WHERE x IS NOT NULL] AS interested_in,
       [x IN collect(DISTINCT CASE WHEN NOT (p)-[:MEMBER_OF]->(iw) THEN iw.name END)
         WHERE x IS NOT NULL] AS awaiting_assignment_in,
       count(DISTINCT CASE WHEN org.is_organizer THEN org END) AS facilitated_count
ORDER BY CASE WHEN toLower(name) = toLower($name) THEN 0 ELSE 1 END, name
LIMIT 1
"""

GET_PERSON_TASKS = f"""
MATCH (p:Person {{name: $name}})-[:ASSIGNED_TO]->(t:Task)
WHERE t.status IN $open_statuses
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
WITH {_TASK_FIELDS}
RETURN * ORDER BY status, description
"""

COUNT_PERSON_DONE = """
MATCH (:Person {name: $name})-[:ASSIGNED_TO]->(t:Task)
WHERE t.status = 'done'
RETURN count(t) AS count
"""

GET_PERSON_MEETINGS = f"""
MATCH (:Person {{name: $name}})-[:ATTENDED]->(m:Meeting)
{_MEETING_MATCH}
WITH {_MEETING_FIELDS}
RETURN * ORDER BY date DESC LIMIT $limit
"""

GET_WORKGROUP = """
MATCH (w:Workgroup)
WHERE w.slug = $workgroup OR toLower(w.name) = toLower($workgroup)
   OR toLower(w.name) CONTAINS toLower($workgroup)
RETURN w.slug AS slug, w.name AS name, w.description AS description
ORDER BY CASE WHEN w.slug = $workgroup THEN 0 ELSE 1 END, name LIMIT 1
"""

GET_WORKGROUP_MEMBERS = """
MATCH (p:Person)-[r:MEMBER_OF]->(:Workgroup {slug: $workgroup})
RETURN p.name AS name, r.source AS source ORDER BY name
"""

FIND_INTERESTED_UNASSIGNED = """
MATCH (p:Person)-[:INTERESTED_IN]->(w:Workgroup)
MATCH (p)-[:SUBMITTED]->(a:VolunteerApplication)
WHERE NOT (p)-[:MEMBER_OF]->(w)
  AND a.status <> 'declined' AND a.status <> 'withdrawn'
  AND ($workgroup IS NULL OR w.slug = $workgroup)
RETURN p.name AS name, w.slug AS workgroup, w.name AS workgroup_name,
       a.status AS application_status, coalesce(a.availability, '') AS availability,
       coalesce(a.skills, []) AS skills, coalesce(a.interests, []) AS interests
ORDER BY workgroup_name, name
"""

GET_WORKGROUP_TASKS = f"""
MATCH (t:Task)-[:BELONGS_TO]->(w:Workgroup {{slug: $workgroup}})
WHERE t.status IN $open_statuses
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
WITH {_TASK_FIELDS}
RETURN * ORDER BY status, description
"""

COUNT_WORKGROUP_DONE = """
MATCH (t:Task)-[:BELONGS_TO]->(:Workgroup {slug: $workgroup})
WHERE t.status = 'done'
RETURN count(t) AS count
"""

LIST_DECISIONS = """
MATCH (m:Meeting)-[:DECIDED]->(d:Decision)
OPTIONAL MATCH (d)-[:CONCERNS]->(w:Workgroup)
WITH d, w, collect(DISTINCT m.id) AS meetings, max(m.date) AS date
WHERE $workgroup IS NULL OR w.slug = $workgroup
RETURN d.statement AS statement, w.slug AS workgroup, w.name AS workgroup_name,
       date, meetings
ORDER BY date DESC, statement LIMIT $limit
"""

GET_WORKGROUP_MEETINGS = f"""
MATCH (m:Meeting)-[:DISCUSSED]->(:Workgroup {{slug: $workgroup}})
{_MEETING_MATCH}
WITH {_MEETING_FIELDS}
RETURN * ORDER BY date DESC LIMIT $limit
"""

# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

# One full-text query per label. Scores are normalised by the best score inside
# that index before the labels are merged, which is NeoCarta's trick for making
# results from separate indexes comparable. Raw Lucene scores are not.
FULL_TEXT_SEARCH = """
CALL {
  CALL db.index.fulltext.queryNodes('meeting_full_text_index', $query, {limit: $top_k})
  YIELD node, score
  WITH collect({node: node, score: score}) AS rows, max(score) AS best
  UNWIND rows AS row
  RETURN row.node AS node, row.score / best AS score, 'meeting' AS kind
UNION
  CALL db.index.fulltext.queryNodes('task_full_text_index', $query, {limit: $top_k})
  YIELD node, score
  WITH collect({node: node, score: score}) AS rows, max(score) AS best
  UNWIND rows AS row
  RETURN row.node AS node, row.score / best AS score, 'task' AS kind
UNION
  CALL db.index.fulltext.queryNodes('decision_full_text_index', $query, {limit: $top_k})
  YIELD node, score
  WITH collect({node: node, score: score}) AS rows, max(score) AS best
  UNWIND rows AS row
  RETURN row.node AS node, row.score / best AS score, 'decision' AS kind
UNION
  CALL db.index.fulltext.queryNodes('workgroup_full_text_index', $query, {limit: $top_k})
  YIELD node, score
  WITH collect({node: node, score: score}) AS rows, max(score) AS best
  UNWIND rows AS row
  RETURN row.node AS node, row.score / best AS score, 'workgroup' AS kind
}
WITH node, score, kind WHERE kind IN $kinds
RETURN node, score, kind ORDER BY score DESC LIMIT $limit
"""

VECTOR_SEARCH = """
CALL {
  CALL db.index.vector.queryNodes('meeting_embedding_index', $top_k, $embedding)
  YIELD node, score RETURN node, score, 'meeting' AS kind
UNION
  CALL db.index.vector.queryNodes('task_embedding_index', $top_k, $embedding)
  YIELD node, score RETURN node, score, 'task' AS kind
UNION
  CALL db.index.vector.queryNodes('decision_embedding_index', $top_k, $embedding)
  YIELD node, score RETURN node, score, 'decision' AS kind
UNION
  CALL db.index.vector.queryNodes('workgroup_embedding_index', $top_k, $embedding)
  YIELD node, score RETURN node, score, 'workgroup' AS kind
}
WITH node, score, kind WHERE kind IN $kinds
RETURN node, score, kind ORDER BY score DESC LIMIT $limit
"""

# Hybrid: normalised full-text and cosine scores, blended by $alpha. Neo4j's
# vector index already returns a 0..1 cosine score, so only the full-text side
# needs normalising.
HYBRID_SEARCH = """
CALL {
  CALL {
    CALL db.index.fulltext.queryNodes('meeting_full_text_index', $query, {limit: $top_k})
    YIELD node, score
    WITH collect({node: node, score: score}) AS rows, max(score) AS best
    UNWIND rows AS row RETURN row.node AS node, row.score / best AS score, 'meeting' AS kind
  UNION
    CALL db.index.fulltext.queryNodes('task_full_text_index', $query, {limit: $top_k})
    YIELD node, score
    WITH collect({node: node, score: score}) AS rows, max(score) AS best
    UNWIND rows AS row RETURN row.node AS node, row.score / best AS score, 'task' AS kind
  UNION
    CALL db.index.fulltext.queryNodes('decision_full_text_index', $query, {limit: $top_k})
    YIELD node, score
    WITH collect({node: node, score: score}) AS rows, max(score) AS best
    UNWIND rows AS row RETURN row.node AS node, row.score / best AS score, 'decision' AS kind
  UNION
    CALL db.index.fulltext.queryNodes('workgroup_full_text_index', $query, {limit: $top_k})
    YIELD node, score
    WITH collect({node: node, score: score}) AS rows, max(score) AS best
    UNWIND rows AS row RETURN row.node AS node, row.score / best AS score, 'workgroup' AS kind
  }
  RETURN node, score * (1 - $alpha) AS score, kind
UNION
  CALL {
    CALL db.index.vector.queryNodes('meeting_embedding_index', $top_k, $embedding)
    YIELD node, score RETURN node, score, 'meeting' AS kind
  UNION
    CALL db.index.vector.queryNodes('task_embedding_index', $top_k, $embedding)
    YIELD node, score RETURN node, score, 'task' AS kind
  UNION
    CALL db.index.vector.queryNodes('decision_embedding_index', $top_k, $embedding)
    YIELD node, score RETURN node, score, 'decision' AS kind
  UNION
    CALL db.index.vector.queryNodes('workgroup_embedding_index', $top_k, $embedding)
    YIELD node, score RETURN node, score, 'workgroup' AS kind
  }
  RETURN node, score * $alpha AS score, kind
}
WITH node, kind, sum(score) AS score WHERE kind IN $kinds
RETURN node, score, kind ORDER BY score DESC LIMIT $limit
"""
