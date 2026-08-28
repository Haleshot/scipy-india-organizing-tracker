# Deploying

Push to a repository under the `scipy-india` organization, then set Settings →
Pages → Source to **GitHub Actions**. The first deployment works on the committed
fixture snapshot with no secrets and no database.

For real data the simple route is to run the refresh on a laptop against the
real Doc, commit `web/public/data/graph.json`, and push. That keeps every
credential off GitHub. `.github/workflows/refresh-graph.yml` runs the pipeline in
Actions instead, but it needs a Neo4j the runner can reach, which a container on
your laptop is not.

The frontend has no build step. `web/public` is the deployable directory,
Cytoscape.js is vendored rather than pulled from a CDN, every URL is relative and
routing is done with the hash, so the site behaves the same at a project URL as
at the root. To check that before deploying:

```bash
mkdir -p /tmp/pages/<repo-name> && cp -R web/public/* /tmp/pages/<repo-name>/
python -m http.server 8000 --directory /tmp/pages
```

## Using the real Google Doc

Two routes, and they behave differently enough to matter.

Downloading the Doc as Markdown by hand is what the fixture workflow assumes,
and the deterministic parser reads it directly. Pointing CocoIndex at the Doc
instead means setting `MEETING_NOTES_SOURCE=google_drive`, and the connector
exports Google Docs as **plain text**, not Markdown. Headings lose their `#` and
bullets disappear. That is why the template is built on labels rather than
markup, and why
[tests/test_note_formats.py](../tests/test_note_formats.py) parses both
representations of the same meeting and asserts the results are identical.

For the Drive route you need a Google Cloud service account and its JSON key.
Share the Drive folder with the service account's email address, the one ending
`@project.iam.gserviceaccount.com`; this is the step people miss, and the API
returns an empty folder rather than an error. Then put the folder id from the
URL in `GOOGLE_DRIVE_ROOT_FOLDER_IDS`. CocoIndex's
[walkthrough](https://cocoindex.io/docs/connectors/google_drive/) is the
reference.

Whether to also switch to `MEETING_EXTRACTOR=llm` depends on how the notes get
written. If the team fills in the template, the deterministic parser handles the
plain-text export fine and is worth keeping for being predictable. If minutes
get taken as free prose, the LLM extractor is the only thing that will cope.
There is no live watching for Drive: the connector scans, so a refresh on a
schedule is the right shape there.

## Evaluating the LLM extractor

The deterministic parser is covered by tests. The LLM extractor has never been
run against anything in this repository, because there are no API credentials
here. `scripts/eval_extraction.py` is how to check it when you have a key.

```bash
export OPENAI_API_KEY=...
python scripts/eval_extraction.py --compare data/meeting_notes/scipy-india-2026-meeting-notes.md
python scripts/eval_extraction.py --ground ~/Downloads/"PyConf Hyderabad 2025 Meeting Notes.md"
python scripts/eval_extraction.py --resolution data/meeting_notes/*.md
```

`--compare` diffs the LLM against the deterministic parse on a document both can
read, so every difference is a nameable error. `--ground` audits LLM output
against the source text on prose minutes where there is no baseline; it cannot
tell you what the model missed, but it catches what it made up. `--resolution`
compares the two person resolvers over the same name set.

Without credentials the script exits 2 and says so rather than pretending. It is
not part of `pytest`, because it costs money and its output is a judgement call.
