# Editing these docs

Every page here is a Markdown file in
[`docs/`](https://github.com/Haleshot/scipy-india-organizing-tracker/tree/main/docs).
If something is wrong or missing, fixing it is editing a file.

## The quickest way

Each page has a pencil icon at the top right. It opens that exact file in
GitHub's editor, and saving offers to open a pull request. No clone, no local
setup.

Good for a wrong command, a stale link, a sentence that does not parse.

## Locally

Worth it for anything larger, because you can see it before anyone else does.

```bash
pip install zensical
zensical serve
```

That serves the docs at <http://localhost:8000> and rebuilds as you save.

```bash
zensical build   # writes site/
```

The build fails on a link to a page or an anchor that does not exist, which
catches most mistakes before review.

## Adding a page

Write the file, then add it to the nav in
[`zensical.toml`](https://github.com/Haleshot/scipy-india-organizing-tracker/blob/main/zensical.toml):

```toml title="zensical.toml"
nav = [
  { "Understanding it" = [
    "reading-the-dashboard.md",
    "your-new-page.md",
  ] },
]
```

A page missing from the nav is still built and still reachable by URL, so CI
checks for that: every nav entry has to point at a file that exists.

## What is available on a page

Standard Markdown, plus a few things worth knowing about.

=== "Admonitions"

    ```markdown
    !!! warning "Docker and Desktop cannot both run"
        They both want port 7687.

    ??? example "A cron entry, if you want one"
        Collapsed by default. Good for detail most readers can skip.
    ```

    `note`, `tip`, `warning`, `danger`, `info`, `success`, `example`. Three
    question marks instead of three exclamation marks makes it collapsible.

=== "Tabs"

    ```markdown
    === "Docker"
        Nothing to install beyond Docker itself.

    === "Neo4j Desktop"
        Better if you want to poke at the graph by hand.
    ```

    Good for genuine alternatives. Bad for sequential steps, since a reader
    following along will miss whichever tab is hidden.

=== "Diagrams"

    ````markdown
    ```mermaid
    flowchart LR
        doc["Google Doc"] --> coco["CocoIndex"] --> neo[("Neo4j")]
    ```
    ````

    Flowcharts, sequence, state, class and entity-relationship diagrams. Pie
    and gantt charts render but do not survive a phone screen, so they are best
    avoided.

=== "Cards"

    ```markdown
    <div class="grid cards" markdown>

    -   __Just want to look at it?__

        ---

        The dashboard is the main thing.

        [Reading the dashboard](reading-the-dashboard.md)

    </div>
    ```

    For a page that is mostly signposting, like the home page. Not for content.

Code blocks take a title, which is worth using whenever the block is a file
rather than a command:

````markdown
```bash title=".env"
ISSUE_SOURCE=github
```
````

## House style

There is a test for this, `tests/test_writing_style.py`, and it will fail the
build rather than leave a comment.

No em dashes or en dashes. Sentence case in headings, so "Adding a person" and
not "Adding A Person". No emoji in headings. Prose over bullet lists unless the
thing genuinely is a list, and at most two bullets between paragraphs.

Beyond what the test checks: write the way you would explain it to someone
sitting next to you. Say what a thing does before saying how to configure it,
and if a step has a gotcha, put the gotcha next to the step rather than in a
troubleshooting section nobody reads.
