# How AI is used

Every default in this project is off. Build the graph as it ships and no model
runs, no text leaves your machine, and no API key is needed. The dashboard you
are looking at was built that way.

There are three places you can turn a model on, and each one is a trade you
should make deliberately, because two of them send the meeting notes to a
company you do not control.

## What is on by default

Reading the notes is done by a parser, not a model. It looks for lines starting
`Meeting:`, `Task:`, `Owner:` and so on, and it does exactly what those lines
say. An empty `Owner:` produces a task with no owner rather than a guess about
who probably has it.

Working out that "Agriya" and "Agriya Khetarpal" are one person is string
comparison after folding case and punctuation. Names that do not match stay
separate. `config/people.yaml` handles the cases no algorithm could get right,
such as a GitHub login, by writing the answer down.

Both of those are boring on purpose. A wrong owner on a task is worse than a
missing one, because a missing owner is visible and a wrong one is not.

## Optional: a model reads the notes

```bash
MEETING_EXTRACTOR=llm
LLM_MODEL=openai/gpt-5-mini
OPENAI_API_KEY=...
```

Worth it if your team writes minutes as prose and nobody is going to type
`Owner:` during a call. The parser needs those labels; a model does not.

**What gets sent:** the full text of each meeting section, once per section, and
again whenever that section changes. That is everything written in the notes:
names, what people said, what was decided, anything somebody typed into the
document during the call.

Model output is constrained to a schema, and the prompt tells it not to infer
anything the text does not state. It is still a language model, so
`scripts/eval_extraction.py` exists to diff it against the parser on a document
both can read. Run that before trusting a graph built this way.

## Optional: a model helps merge names

```bash
PERSON_RESOLUTION=embedding
RESOLUTION_LLM_MODEL=openai/gpt-5-mini
```

Worth it if the same person appears as "Malayaja", "Malayaja C" and "malayaja c"
across months of notes and adding each spelling to `people.yaml` has become a
chore.

**What gets sent:** names only. Every name is embedded, close pairs are
shortlisted by vector distance, and only those pairs go to the model to confirm.
No meeting text, no decisions, no task descriptions. This is the smaller of the
two exposures by a wide margin.

## Optional: semantic search

```bash
SEARCH_EMBEDDING_MODEL=Snowflake/snowflake-arctic-embed-xs
```

Turns the search tool from keyword matching into hybrid retrieval, so "who is
handling money" finds tasks about sponsorship and budget.

**What gets sent: nothing.** That model name is a sentence-transformers model
that downloads once and runs on your machine. No key, no network after the
download. A LiteLLM `provider/model` string works too if you would rather use a
hosted service, and that one does send text, so the local model is the default
recommendation rather than an afterthought.

Volunteer application text is never indexed either way. Somebody's free-text
answer about themselves is not something to make semantically searchable.

## Optional: an agent queries the graph

The MCP server gives an agent thirteen read-only tools. Whatever the agent sees
goes wherever that agent sends it, which is between you and whichever assistant
you are running; this project does not choose it for you.

The server itself makes no model calls. It reads Neo4j and returns rows. It also
cannot write: queries run under `RoutingControl.READ`, so there is no tool that
edits the notes, closes an issue, or changes the graph.

## If you are deciding whether to send notes to a provider

Some things worth checking before you do.

Meeting notes name people who never agreed to that. A volunteer's name, an
opinion somebody voiced in a call, a sponsor conversation that has not gone
anywhere yet. Sending those to an API is a decision about other people's
information, not only your own.

Check whether the provider trains on API input. Most do not by default on paid
tiers, and free tiers are often the exception. OpenRouter passes requests
through to whichever upstream you route to, so the policy that matters is that
upstream's, not OpenRouter's.

Then consider whether you need it. If your team fills in the template, the
parser handles it and the answer is no. `MEETING_EXTRACTOR=llm` earns its
exposure when the alternative is nobody keeping structured notes at all.

If you want the merging help without sending meeting text anywhere, turn on
`PERSON_RESOLUTION=embedding` and leave `MEETING_EXTRACTOR=markdown`. Names go
out, notes stay put.
