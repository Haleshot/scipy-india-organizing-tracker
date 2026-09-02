# Publishing the dashboard

The dashboard is a static site with no build step. `web/public` is the
deployable directory as it stands: Cytoscape.js is vendored rather than pulled
from a CDN, every URL is relative, and routing uses the hash, so the site
behaves the same at a project URL as it does at the root.

## GitHub Pages

Push to a repository under the `scipy-india` organization, then set Settings,
Pages, Source to **GitHub Actions**. The first deployment works on the committed
snapshot with no secrets and no database, which is a useful way to check the
plumbing before pointing anything real at it.

To check a project-path deployment locally first, since that is where relative
URLs usually break:

```bash
mkdir -p /tmp/pages/<repo-name> && cp -R web/public/* /tmp/pages/<repo-name>/
python -m http.server 8000 --directory /tmp/pages
```

## Keeping it current

The straightforward route is to run the refresh on a laptop against the real
sources, commit `web/public/data/graph.json`, and push. Every credential stays
off GitHub, and the thing being published is a file somebody looked at.

`.github/workflows/refresh-graph.yml` runs the pipeline in Actions instead. It
needs a Neo4j the runner can reach, which a container on your laptop is not, so
it wants a hosted instance such as Aura before it is any use.

The workflow refuses to deploy a snapshot whose profile is not `public`. See
[Privacy boundary](privacy.md) for what that distinction covers.

## Evaluating the LLM extractor

Worth reading before switching `MEETING_EXTRACTOR=llm` on a graph anyone will
rely on. The deterministic parser is covered by tests; a language model is not
something tests can cover the same way, so there is a harness instead:

```bash
export OPENAI_API_KEY=...
python scripts/eval_extraction.py --compare data/meeting_notes/scipy-india-2026-meeting-notes.md
python scripts/eval_extraction.py --ground ~/Downloads/"some prose minutes.md"
python scripts/eval_extraction.py --resolution data/meeting_notes/*.md
```

`--compare` diffs the LLM against the deterministic parse on a document both can
read, so every difference is a nameable error. `--ground` audits LLM output
against the source text where there is no baseline to diff against; it cannot
tell you what the model missed, but it catches what it invented. `--resolution`
compares the two person resolvers over the same set of names.

Without credentials the script exits 2 and says so. It is not part of `pytest`,
because it costs money to run and its output is a judgement rather than a pass
or a fail.
