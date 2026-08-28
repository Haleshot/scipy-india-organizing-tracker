// SciPy India organizing queries.
//
// Paste any of these into Neo4j Browser at http://localhost:7474, or run the
// lot with:
//
//     python scripts/run_queries.py
//     python scripts/run_queries.py --name open-tasks
//
// Each query is introduced by a `// @name:` line. run_queries.py splits on
// those, so keep the format if you add more.

// @name: open-tasks
// What is still open? Anything not done and not dropped, newest meeting first.
MATCH (t:Task)
WHERE t.status IN ['open', 'in_progress', 'blocked', 'unknown']
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
RETURN t.description AS task,
       t.status      AS status,
       t.due         AS due,
       w.name        AS workgroup,
       collect(DISTINCT owner.name) AS owners
ORDER BY status, task;

// @name: unowned-tasks
// Which tasks have nobody on the hook for them?
MATCH (t:Task)
WHERE NOT (:Person)-[:ASSIGNED_TO]->(t)
  AND t.status <> 'done' AND t.status <> 'dropped'
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
RETURN t.description AS task, t.status AS status, t.due AS due, w.name AS workgroup
ORDER BY workgroup, task;

// @name: person-workload
// Everything one person owns. Change the name.
MATCH (p:Person {name: 'Devika Nair'})-[:ASSIGNED_TO]->(t:Task)
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
RETURN t.description AS task, t.status AS status, t.due AS due, w.name AS workgroup
ORDER BY status, task;

// @name: workgroup-members
// Who is in each workgroup, and did the assignment come from the notes or a form?
MATCH (w:Workgroup)
OPTIONAL MATCH (p:Person)-[m:MEMBER_OF]->(w)
RETURN w.name AS workgroup,
       collect(DISTINCT p.name + ' (' + m.source + ')') AS members
ORDER BY workgroup;

// @name: interested-not-assigned
// People who asked for a workgroup and are still waiting. The follow-up list.
MATCH (p:Person)-[:INTERESTED_IN]->(w:Workgroup)
WHERE NOT (p)-[:MEMBER_OF]->(w)
OPTIONAL MATCH (p)-[:SUBMITTED]->(a:VolunteerApplication)
RETURN w.name AS workgroup,
       p.name AS person,
       a.status AS application_status,
       a.availability AS availability
ORDER BY workgroup, person;

// @name: task-origin
// Which meeting created a task, which have touched it since, and what status did
// it carry each time. CREATED_ACTION marks the origin; TOUCHED_ACTION is every
// appearance including the first.
MATCH (t:Task)
WHERE t.description = 'Port the 2025 site template and put up a holding page'
MATCH (creator:Meeting)-[:CREATED_ACTION]->(t)
MATCH (m:Meeting)-[touch:TOUCHED_ACTION]->(t)
WITH t, creator, touch ORDER BY touch.date
RETURN t.description AS task,
       t.status       AS current_status,
       t.id           AS task_id,
       creator.date   AS created_on,
       creator.source_ref AS created_in_section,
       collect(toString(touch.date) + ' = ' + touch.status) AS history;

// @name: meetings-by-topic
// Which meetings discussed something? Case-insensitive substring over the
// recorded topics, summary and title.
WITH 'venue' AS term
MATCH (m:Meeting)
WHERE toLower(m.title) CONTAINS toLower(term)
   OR toLower(m.summary) CONTAINS toLower(term)
   OR any(topic IN m.topics WHERE toLower(topic) CONTAINS toLower(term))
RETURN m.date AS date, m.title AS meeting, m.topics AS topics
ORDER BY date DESC;

// @name: workgroup-decisions
// What has been decided about one workgroup?
MATCH (m:Meeting)-[:DECIDED]->(d:Decision)-[:CONCERNS]->(w:Workgroup {slug: 'sponsorship'})
RETURN m.date AS date, m.title AS meeting, d.statement AS decision
ORDER BY date DESC;

// @name: latest-meeting
// What changed in the most recent meeting: decisions taken, tasks touched,
// and who joined a workgroup.
MATCH (m:Meeting)
WITH m ORDER BY m.date DESC LIMIT 1
OPTIONAL MATCH (m)-[:DECIDED]->(d:Decision)
OPTIONAL MATCH (m)-[touch:TOUCHED_ACTION]->(t:Task)
OPTIONAL MATCH (m)-[:DISCUSSED]->(w:Workgroup)
RETURN m.date AS date,
       m.title AS meeting,
       collect(DISTINCT d.statement) AS decisions,
       collect(DISTINCT t.description + ' [' + touch.status + ']') AS tasks,
       collect(DISTINCT w.name) AS workgroups;

// @name: latest-changes
// What moved between the two most recent meetings. TOUCHED_ACTION carries the
// status at each meeting, so this is a direct comparison rather than a replay.
MATCH (m:Meeting) WITH m ORDER BY m.date DESC LIMIT 2
WITH collect(m) AS recent
WITH recent[0] AS newest, recent[1] AS previous
MATCH (newest)-[now:TOUCHED_ACTION]->(t:Task)
OPTIONAL MATCH (previous)-[before:TOUCHED_ACTION]->(t)
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
WITH newest, previous, t, w, now, before
WHERE before IS NULL OR before.status <> now.status
RETURN toString(previous.date) + ' -> ' + toString(newest.date) AS between,
       w.name AS workgroup,
       t.description AS task,
       coalesce(before.status, 'not mentioned') AS was,
       now.status AS now
ORDER BY workgroup, task;

// @name: task-identity-audit
// Action items that share a description. They are separate tasks only because
// the workgroup or an explicit id kept them apart; worth a look when a new
// document is imported.
MATCH (t:Task)
WITH t.description AS description, collect(t) AS tasks
WHERE size(tasks) > 1
UNWIND tasks AS t
OPTIONAL MATCH (t)-[:BELONGS_TO]->(w:Workgroup)
OPTIONAL MATCH (owner:Person)-[:ASSIGNED_TO]->(t)
RETURN description, t.id AS task_id, t.identity_basis AS kept_apart_by,
       w.name AS workgroup, collect(owner.name) AS owners
ORDER BY description, task_id;

// @name: provenance
// Why does the graph believe this? Source document, section, extraction mode and
// the meeting that first recorded it, for every open unowned action item.
MATCH (t:Task)
WHERE t.status IN ['open', 'in_progress', 'blocked', 'unknown']
  AND NOT (:Person)-[:ASSIGNED_TO]->(t)
MATCH (creator:Meeting)-[:CREATED_ACTION]->(t)
RETURN t.description AS task,
       t.identity_basis AS identity_from,
       t.extraction_mode AS extracted_by,
       creator.date AS first_recorded,
       creator.source_ref AS source
ORDER BY first_recorded;

// @name: idle-volunteers
// Volunteers with no open task assigned to them. Where to look when something
// needs picking up.
MATCH (p:Person)-[:SUBMITTED]->(a:VolunteerApplication)
WHERE NOT (p)-[:ASSIGNED_TO]->(:Task {status: 'open'})
  AND NOT (p)-[:ASSIGNED_TO]->(:Task {status: 'in_progress'})
OPTIONAL MATCH (p)-[:INTERESTED_IN]->(w:Workgroup)
RETURN p.name AS person,
       a.status AS application_status,
       a.availability AS availability,
       collect(DISTINCT w.name) AS interested_in
ORDER BY person;

// @name: tasks-by-workgroup
// Open task count per workgroup, including the workgroups with none.
MATCH (w:Workgroup)
OPTIONAL MATCH (t:Task)-[:BELONGS_TO]->(w)
WHERE t.status IN ['open', 'in_progress', 'blocked', 'unknown']
RETURN w.name AS workgroup, count(t) AS open_tasks
ORDER BY open_tasks DESC, workgroup;

// @name: meeting-attendance
// Who showed up where, and who ran it.
MATCH (p:Person)-[r:ATTENDED]->(m:Meeting)
RETURN m.date AS date, m.title AS meeting,
       collect(DISTINCT CASE WHEN r.is_organizer THEN p.name + ' (facilitator)' ELSE p.name END) AS attendees
ORDER BY date DESC;

// @name: person-profile
// One person, everything: meetings, tasks, workgroups. Change the name.
MATCH (p:Person {name: 'Priya Vasudevan'})
OPTIONAL MATCH (p)-[:ATTENDED]->(m:Meeting)
OPTIONAL MATCH (p)-[:ASSIGNED_TO]->(t:Task)
OPTIONAL MATCH (p)-[:MEMBER_OF]->(w:Workgroup)
OPTIONAL MATCH (p)-[:INTERESTED_IN]->(iw:Workgroup)
RETURN p.name AS person,
       collect(DISTINCT toString(m.date) + ' ' + m.title) AS meetings,
       collect(DISTINCT t.description + ' [' + t.status + ']') AS tasks,
       collect(DISTINCT w.name) AS member_of,
       collect(DISTINCT iw.name) AS interested_in;
