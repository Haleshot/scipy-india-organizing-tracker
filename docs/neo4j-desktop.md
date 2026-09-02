# Running it on Neo4j Desktop

Docker is the quickest way to get a database up, but it gives you a black box.
Neo4j Desktop gives you the same database with a query editor and a graph
visualiser attached, which is what you want if you would rather poke at the data
than read about it.

## Create the instance

Download [Neo4j Desktop](https://neo4j.com/download/), open it, and create a
new local instance. Three things matter:

Give it a name you will recognise later, such as
`SciPy-India-CocoIndex-Meeting-Notes`. Set a password and remember it; this is
the one thing you cannot recover from the interface afterwards. Leave the
version at whatever Desktop offers, which is 5.x and is what this expects.

Then press Start. The instance takes a few seconds to come up, and Desktop shows
it as running with its ports listed: 7687 for Bolt, which is what the pipeline
connects on, and 7474 for the browser interface.

!!! warning "Docker and Desktop cannot both run"

    They both want port 7687. If you have been using the Docker setup, run
    `docker compose down` before starting the Desktop instance, or Desktop
    starts and then fails to bind. The symptom is confusing: the pipeline
    connects successfully and then rejects your password, because it reached
    the *other* database.

## Point the pipeline at it

In `.env`:

```bash
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=the password you set
NEO4J_DATABASE=neo4j
```

`bolt://` rather than `neo4j://` on purpose. Desktop shows you a `neo4j://` URL,
which is the routing protocol for a cluster. A single local instance is not a
cluster, and `bolt://` connects to it directly with one less thing to go wrong.

Then build the graph:

```bash
./scripts/refresh.sh
```

## Look at the graph in Desktop

Open the instance in Desktop and go to its query editor. The whole graph is
small enough to draw at once:

```cypher
MATCH (n)-[r]->(m) RETURN n, r, m
```

That will be a hairball. These are more useful.

**What is still open, and who has it.**

```cypher
MATCH (t:Task)
WHERE t.status IN ['open', 'in_progress', 'blocked']
OPTIONAL MATCH (p:Person)-[:ASSIGNED_TO]->(t)
RETURN t.description AS task, t.status AS status,
       collect(p.name) AS owners, t.due AS due
ORDER BY size(collect(p.name)), t.description
```

**Everything one person touches.**

```cypher
MATCH (p:Person {name: 'Agriya Khetarpal'})
OPTIONAL MATCH (p)-[:ASSIGNED_TO]->(t:Task)
OPTIONAL MATCH (p)-[:WORKS_ON]->(i:Issue)
OPTIONAL MATCH (p)-[:MEMBER_OF]->(w:Workgroup)
RETURN p, t, i, w
```

**How one action item moved over time.** The graph keeps every appearance of a
task, not just its latest state, so this reads as a history.

```cypher
MATCH (m:Meeting)-[touch:TOUCHED_ACTION]->(t:Task)
WHERE t.id CONTAINS 'sponsorship-deck'
RETURN m.date AS date, touch.status AS status, touch.due AS due
ORDER BY date
```

**Where the notes and the tracker meet.**

```cypher
MATCH (t:Task)-[:TRACKED_BY]->(i:Issue)
RETURN t.description AS task, t.status AS from_the_notes,
       i.key AS issue, i.state AS on_github
```

More of these live in [The graph model](graph-model.md), which explains what the
labels and relationships mean.

## Asking in plain language instead

If you would rather not write Cypher, the MCP server does this for you and an
agent can drive it. That is [Asking questions](asking-questions.md).
