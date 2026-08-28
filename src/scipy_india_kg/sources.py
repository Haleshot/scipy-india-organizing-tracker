"""Where meeting notes come from.

Both supported sources yield the same thing, ``(key, FileLike)`` pairs, where
``FileLike`` has an async ``read_text()``. That is CocoIndex's own file
abstraction, so switching between them changes one environment variable and
nothing else in the pipeline.

``local``
    ``cocoindex.connectors.localfs.walk_dir`` over ``MEETING_NOTES_DIR``. Runs
    with no credentials, which is what makes the fixture demo possible. Set
    ``MEETING_NOTES_FILE`` to pin it to one export.

``google_drive``
    ``cocoindex.connectors.google_drive.GoogleDriveSource``, exactly as the
    upstream example uses it. This is the long-term source of truth: point it at
    the folder holding the canonical SciPy India notes doc and share that folder
    with the service account.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from cocoindex.connectors import google_drive, localfs
from cocoindex.resources.file import PatternFilePathMatcher


class MeetingNoteSource(Protocol):
    """Anything that can hand the pipeline keyed note files."""

    def items(self) -> Any:
        """Async-iterable of ``(key, file)`` where ``file`` has ``read_text()``."""


# Google Docs come back from the Drive connector as **plain text**, not Markdown:
# the connector exports `application/vnd.google-apps.document` that way, so `##`
# headings and `-` bullets are gone by the time the pipeline sees them. That is
# why the note template in docs/meeting-notes-template.md is built out of plain
# labels; see tests/test_note_formats.py, which parses both representations of
# the same meeting and asserts they agree.
DRIVE_MIME_TYPES = (
    "application/vnd.google-apps.document",
    "text/markdown",
    "text/plain",
)

NOTE_SUFFIXES = (".md", ".markdown", ".txt")


class _LocalNoteSource:
    """Walks ``MEETING_NOTES_DIR`` for note files.

    ``MEETING_NOTES_FILE`` narrows it to one, which is what you want when the
    directory holds a single canonical export and you keep re-downloading it
    under whatever name Google gives you.
    """

    def __init__(self, directory: Path, *, live: bool = False, filename: str | None = None) -> None:
        self._directory = directory
        self._live = live
        self._filename = filename

    def items(self) -> Any:
        patterns = (
            [self._filename] if self._filename else [f"**/*{suffix}" for suffix in NOTE_SUFFIXES]
        )
        return localfs.walk_dir(
            self._directory,
            recursive=not self._filename,
            live=self._live,
            path_matcher=PatternFilePathMatcher(included_patterns=patterns),
        ).items()


def meeting_note_source(*, live: bool = False) -> MeetingNoteSource:
    """Build the configured meeting-note source from the environment."""
    kind = os.environ.get("MEETING_NOTES_SOURCE", "local").strip().lower()

    if kind == "local":
        directory = Path(os.environ.get("MEETING_NOTES_DIR", "./data/meeting_notes"))
        if not directory.is_dir():
            raise ValueError(f"MEETING_NOTES_DIR does not exist: {directory.resolve()}")
        filename = os.environ.get("MEETING_NOTES_FILE", "").strip() or None
        if filename and not (directory / filename).is_file():
            raise ValueError(
                f"MEETING_NOTES_FILE={filename!r} is not in {directory.resolve()}. "
                "Either drop the export in under that name, or clear the variable "
                "to read every note file in the directory."
            )
        return _LocalNoteSource(directory, live=live, filename=filename)

    if kind == "google_drive":
        credential_path = _require("GOOGLE_SERVICE_ACCOUNT_CREDENTIAL")
        root_folder_ids = [
            folder.strip()
            for folder in _require("GOOGLE_DRIVE_ROOT_FOLDER_IDS").split(",")
            if folder.strip()
        ]
        return google_drive.GoogleDriveSource(
            service_account_credential_path=credential_path,
            root_folder_ids=root_folder_ids,
            mime_types=DRIVE_MIME_TYPES,
        )

    raise ValueError(f"Unknown MEETING_NOTES_SOURCE={kind!r}. Use 'local' or 'google_drive'.")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(
            f"{name} is required when MEETING_NOTES_SOURCE=google_drive. "
            "Copy .env.example to .env and fill it in."
        )
    return value
