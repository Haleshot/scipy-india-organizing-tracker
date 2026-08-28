# Asking the graph questions

The MCP server and the CLI: the tools they share, how to connect Claude Code
or Claude Desktop, and how search decides what it can offer.

`./scripts/query` is the CLI and `src/scipy_india_kg/mcp/` is the MCP server.
Both call the same `OrganizerGraph`, which is the only thing in the project that
holds retrieval Cypher, so a tool and its CLI twin cannot answer differently.

```bash
./scripts/query describe-graph
./scripts/query list-unassigned-tasks
./scripts/query get-workgroup-context "Website"
./scripts/query search "code of conduct" --json
```

The eleven tools, which are also the eleven CLI subcommands:

| Tool | Arguments | Answers |
| --- | --- | --- |
| `describe_graph` | | what this data is, where it came from, what search is available |
| `list_recent_meetings` | `limit=5` | the last few meetings |
| `get_meeting_context` | `meeting_id=None`, `date=None` | one meeting: attendees, decisions, action items with status transitions |
| `list_open_tasks` | `workgroup=None`, `owner=None`, `limit=50` | what is still open |
| `list_unassigned_tasks` | `workgroup=None`, `limit=50` | open work with no owner |
| `get_task_history` | `task`, `limit=3` | origin, source reference and status history for one item |
| `get_person_context` | `name` | one person: workgroups, open work, meetings, volunteer profile |
| `get_workgroup_context` | `workgroup`, `recent_meetings=3` | where a workgroup stands, in one call |
| `list_recent_decisions` | `workgroup=None`, `limit=10` | decisions, newest first, with their meetings |
| `find_interested_unassigned_volunteers` | `workgroup=None` | who asked for a workgroup and is still waiting |
| `search_organizing_graph` | `query`, `limit=10`, `kinds=None` | open-ended text search |

Everything is read-only, and not merely by convention: queries run under
`RoutingControl.READ`, so Neo4j rejects a write rather than trusting the caller.
There is no arbitrary-Cypher tool and no write tool of any kind.
[tests/test_graph_readonly.py](../tests/test_graph_readonly.py) proves it by
attempting one.

Where that guarantee stops: the server connects with the same Neo4j account the
pipeline writes with, so the credential itself is not read-only. Running over
stdio on your own laptop, that is the same trust boundary as the terminal you
started it from. If this ever gets exposed beyond one machine, give it a
read-only Neo4j role before anything else.

### Connecting Claude Code or Claude Desktop

```bash
python scripts/print_mcp_config.py --write
```

That writes `.mcp.json` in the project root with your absolute paths filled in;
restart Claude Code in this directory and it picks it up. For Claude Desktop,
run the same script without `--write` and merge the `mcpServers` block into
`claude_desktop_config.json`, which lives in `~/Library/Application
Support/Claude/` on macOS and `%APPDATA%/Claude/` on Windows.

No credentials go in that file. The server reads `.env` from the project
directory it is launched in, which is where it already lives. `PYTHONPATH` is
set explicitly rather than relying on `pip install -e .`, because a `.pth` file
is a fragile thing to make a background process depend on.

Then you can ask things like "what open action items still have no owner", "what
did we decide about the website in the last three meetings", or "give me the
current context for Website". The last one is a single
`get_workgroup_context` call. "What changed between the two most recent
meetings" works because `get_meeting_context` returns each item with the status
it held at that meeting and at the previous meeting that touched it, so the diff
is a comparison rather than a replay.

### Search

```bash
python scripts/build_search_indexes.py               # full text, no models
python scripts/build_search_indexes.py --embeddings  # adds vectors, for hybrid
python scripts/build_search_indexes.py --status
```

Full-text costs nothing. `--embeddings` adds a vector index per label using a
local sentence-transformers model, so it needs a one-time model download and no
API key. Set `SEARCH_EMBEDDING_MODEL` to that model in `.env` and the server
upgrades itself to hybrid retrieval; leave it empty and it stays on full text.
A LiteLLM `provider/model` string works too if you would rather use a hosted
provider.

The strategy is chosen for the whole search rather than per label, because
ranking a cosine score for one label against a Lucene score for another produces
numbers that cannot be compared. `search_organizing_graph` is registered only
when an index exists that can serve it, so an agent is never handed a tool that
returns nothing.

Changing the embedding model re-embeds everything, because the model name is
part of the hash that decides what is current. If the new model produces vectors
of a different width the builder stops and tells you to add `--recreate`, since
Neo4j keeps an existing vector index rather than widening it and search would
otherwise go quiet instead of failing.

Volunteer application text is indexed by neither. Somebody's free-text answer
about themselves is not something to make semantically searchable by default.

## What this borrowed from NeoCarta

[NeoCarta](https://github.com/neo4j-labs/neocarta) builds semantic-layer graphs
of databases, and its MCP server is written against that model. None of its
ontology is used here and CocoIndex owns ingestion, but the engineering around
its retrieval layer is worth having.

Reused: capability-gated tool registration, so a search tool is offered only
when an index can serve it; Cypher, result models and tools kept in separate
modules; a CLI that mirrors every MCP tool over one shared implementation;
`RoutingControl.READ` on every query; per-index score normalisation before
merging results, because raw Lucene scores from two indexes are not comparable;
Lucene input sanitisation; and a build-metadata singleton, which is where the
`GraphBuild` node came from.

Not reused: the `Database`/`Schema`/`Table`/`Column` ontology, the connector
framework and its Claude Code skill, since CocoIndex already owns that layer;
the per-label registrar dispatch, which eleven fixed tools do not need; and
LiteLLM as a required embedding dependency, since a local sentence-transformers
model keeps the search path credential-free.
