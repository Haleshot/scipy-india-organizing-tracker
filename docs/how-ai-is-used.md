# How AI is used

Every model in this project is off unless you switch it on. Build the graph as
it ships and nothing runs, nothing leaves your machine, and you need no API key.
The dashboard was built that way.

There are three places you can turn one on. Two of them send text to a company
you do not control, so they are worth thinking about rather than enabling
because they are there.

## What runs by default

Reading the notes is a parser. It looks for lines starting `Meeting:`, `Task:`,
`Owner:` and does what they say. An empty `Owner:` gives you a task with no
owner rather than a guess about who probably has it.

Working out that "Agriya" and "Agriya Khetarpal" are the same person is string
comparison after folding case and punctuation. Anything that does not match
stays separate, and `config/people.yaml` covers the cases no algorithm could
get right, like a GitHub login, by writing the answer down.

Both are dull by design. A wrong owner is worse than a missing one, because you
can see a missing one.

## The three optional models

=== "Reading the notes"

    ```bash title=".env"
    MEETING_EXTRACTOR=llm
    LLM_MODEL=openai/gpt-5-mini
    OPENAI_API_KEY=...
    ```

    Worth it if your team writes minutes as prose and nobody is going to type
    `Owner:` mid-call. The parser needs those labels. A model does not.

    !!! warning "What gets sent"

        The full text of every meeting section, once each, and again whenever a
        section changes. That is everything in the notes: names, what people
        said, what was decided, whatever somebody typed during the call.

    Output is constrained to a schema and the prompt says not to infer anything
    the text does not state, but it is still a language model.
    `scripts/eval_extraction.py` diffs it against the parser on a document both
    can read, so run that before trusting a graph built this way.

=== "Merging names"

    ```bash title=".env"
    PERSON_RESOLUTION=embedding
    RESOLUTION_LLM_MODEL=openai/gpt-5-mini
    ```

    Worth it once the same person shows up as "Malayaja", "Malayaja C" and
    "malayaja c" across months of notes and keeping `people.yaml` current has
    become a chore.

    !!! info "What gets sent"

        Names, and nothing else. Every name is embedded, close pairs get
        shortlisted by distance, and only those pairs go to the model to
        confirm. No meeting text, no decisions, no task descriptions.

    This is much the smaller of the two exposures. If you want the merging help
    without sending notes anywhere, turn this on and leave `MEETING_EXTRACTOR`
    alone.

=== "Search"

    ```bash title=".env"
    SEARCH_EMBEDDING_MODEL=Snowflake/snowflake-arctic-embed-xs
    ```

    Turns search from keyword matching into something that finds sponsorship
    and budget tasks when you ask who is handling money.

    !!! success "What gets sent: nothing"

        That is a sentence-transformers model. It downloads once and runs on
        your machine, with no key and no network after the download.

    A LiteLLM `provider/model` string works too, and that one does send text
    over the wire, which is why the local model is the recommendation rather
    than an afterthought.

    Volunteer application text is never indexed either way.

## Agents

The MCP server hands an agent thirteen read-only tools. Whatever that agent sees
goes wherever the agent sends it, which is between you and whichever assistant
you run.

The server itself makes no model calls. It reads Neo4j and returns rows, and it
cannot write: queries run under `RoutingControl.READ`, so no tool can edit the
notes, close an issue or change the graph.

## Before you send notes to a provider

Meeting notes name people who never agreed to that. A volunteer's name, an
opinion somebody voiced on a call, a sponsor conversation that has not gone
anywhere. Sending those to an API is a decision about other people's
information, not only your own, and worth raising with the team rather than
flipping in `.env`.

Check whether the provider trains on API input. Most paid tiers do not by
default and free tiers often are the exception. OpenRouter passes requests
through to whichever upstream you route to, so the policy that binds is that
upstream's rather than OpenRouter's.

Then ask whether you need it at all. If the team fills in the template, the
parser handles it and the answer is no. Turning on `MEETING_EXTRACTOR=llm` earns
its exposure when the alternative is nobody keeping structured notes.
