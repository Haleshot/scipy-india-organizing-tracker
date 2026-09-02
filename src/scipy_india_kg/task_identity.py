"""Deciding when two action items in the notes are the same action item.

The upstream CocoIndex example keys a task by its description, and this project
leaned on that: an action item repeated in a later meeting is the same task, so
its status moves ``open`` -> ``blocked`` -> ``in_progress`` as the notes record
it. That recurrence is the feature. Description-only identity is what has to go.

"Send the reminder email" will eventually be written by two workgroups about two
different emails, and a description-keyed graph would silently merge them into
one task with one status and two unrelated owners. Nothing would look broken.

So identity is a scoped key, resolved in this order:

1. **An explicit id in the notes.** ``id: cfp-timeline`` on the action-item line
   wins over everything. This is the escape hatch for the case the heuristic
   cannot see: two genuinely different tasks that share a workgroup and a
   description. Give one of them an id and they separate.
2. **Workgroup plus normalised description.** Two workgroups may both "Send the
   reminder email" and stay separate; the same workgroup saying it across four
   meetings stays one task.
3. **Normalised description alone**, scoped to the source document, when the
   notes place the task in no workgroup. This is the old behaviour, kept only
   for the case where there is nothing better to scope by.

Every key is also scoped to the note file, so two documents (last year's notes
and this year's) never merge tasks across them.

Normalisation folds case, whitespace and trailing punctuation, so "Draft the CFP
timeline" and "Draft the CFP timeline." are one task. It does not do anything
cleverer: near-duplicate wording stays two tasks, which is the safe direction to
be wrong in. The graph shows two open items instead of hiding one.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[\s.,;:!?\-–—]+$")

# How the key was derived. Stored on the Task node so an organizer can see which
# rule produced it without re-reading the notes.
IDENTITY_BASES = ("explicit_id", "workgroup_description", "description")

UNSCOPED = "unscoped"


def normalize_description(description: str) -> str:
    """Fold case, whitespace and trailing punctuation. Nothing more."""
    return _TRAILING_PUNCT.sub("", _WHITESPACE.sub(" ", description.strip()).lower())


def _slugify(text: str, *, limit: int = 24) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "task"


@dataclass(frozen=True)
class TaskIdentity:
    """A resolved task key plus the evidence for it."""

    id: str
    basis: str  # one of IDENTITY_BASES
    scope: str  # workgroup slug, or UNSCOPED
    normalized_description: str


def task_identity(
    *,
    note_file: str,
    description: str,
    workgroup: str | None,
    explicit_id: str | None = None,
) -> TaskIdentity:
    """Resolve the stable id for one action item as one meeting recorded it.

    Deterministic: the same inputs give the same id on every run, which is what
    lets CocoIndex reconcile the node incrementally instead of creating a new
    one each time the pipeline runs.
    """
    normalized = normalize_description(description)
    scope = workgroup or UNSCOPED

    if explicit_id:
        basis = "explicit_id"
        readable = _slugify(explicit_id)
        material = f"explicit\x1f{note_file}\x1f{explicit_id.strip().lower()}"
    elif workgroup:
        basis = "workgroup_description"
        readable = _slugify(description)
        material = f"wg\x1f{note_file}\x1f{workgroup}\x1f{normalized}"
    else:
        basis = "description"
        readable = _slugify(description)
        material = f"desc\x1f{note_file}\x1f{normalized}"

    # The "h" is not decoration. A ten-character hex digest is all decimal
    # digits about one time in a hundred, which is indistinguishable from an
    # Indian mobile number to anything scanning for leaked contact details,
    # including this project's own privacy check. The prefix makes that
    # impossible without changing what the digest is.
    digest = "h" + hashlib.sha1(material.encode("utf-8")).hexdigest()[:10]
    return TaskIdentity(
        id=f"{scope}:{readable}:{digest}",
        basis=basis,
        scope=scope,
        normalized_description=normalized,
    )
