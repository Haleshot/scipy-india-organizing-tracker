# Design notes

The dashboard is meant to read as a working document: a meeting agenda, an issue
list, a runbook. Not a product dashboard. Everything below is a constraint that
follows from that, and there is a test for most of them, because every one was
broken at some point in this project's history.

## The rules

Spacing sits on an 8px grid, with 4px as the only half step and 1 to 2px for
optical nudges. There is one accent, `#0054a6`, lifted from the
[SciPy logo](https://scipy.in/2026/_static/logo.svg), and it marks links and the
current nav item and nothing else. Status has colour because status is real
data; nothing else is tinted.

Prefer a rule, an indent or a size change over another container. Boxes appear
in exactly two places, the graph canvas and the record panel beside it, because
those are the only two things that really are panels.

Light is the primary design. Dark is the same decisions inverted, with the page
background matched to `scipy.in/2026` so the two sites sit together.

## Things that are absent on purpose

No gradients, no glow, no capsule buttons, no card grids, no metric-card rows,
no decorative icons, no sparkles, no pulsing status dots, no opacity fades on
hover, and no violet. Those are the defaults a generated interface converges on,
and several of them were here before.

Controls are built once and never rebuilt mid-interaction. Typing in a filter
used to replace the input element on every keystroke, which took the focus and
the caret with it: the field felt broken after one letter. Only the results list
is replaced now.

## The graph legend

The explorer needs five categories told apart, and five arbitrary hues is how a
palette ends up violet and pink for no reason. The colours come from the logo,
darkened where they need to hold up on white:

| Category | Colour | Shape |
| --- | --- | --- |
| Person | `#0054a6` blue | circle |
| Volunteer role | `#007a34` green | circle |
| Meeting | `#5b6570` grey | rounded square |
| Action item | `#8a5d05` amber | circle |
| Decision | `#5b6570` grey | diamond |

The fifth category is told apart by shape rather than a fifth colour.

## The explorer

Drawing sixty-three nodes at once is not a useful view and never was. The
default is people and volunteer roles only, and the way in is to search for one
thing and read its neighbourhood. Meetings, action items and decisions are one
toggle away under **Display**, and the whole graph is still one button away for
anyone who wants it.

Inside a focused view, only people and roles are labelled. Meeting, task and
decision text is long, it collides, and the panel beside the graph is a better
place to read it; a node names itself on hover or selection. Layout runs with
`nodeDimensionsIncludeLabels`, so the words are what get spaced apart rather
than the dots underneath them.

**Fullscreen** uses the Fullscreen API where it is allowed and a fixed-position
fallback where it is not, so it works inside an iframe. Escape leaves either.

## Where the tests are

`tests/test_writing_style.py` checks the prose rules and the visual ones: no em
dashes, sentence-case headings, no emoji in headings, no gradients, no capsules,
no violet, spacing on the grid, and exactly one accent per colour scheme. It is
a house-style lint, not a judgement about whether the design is any good.
