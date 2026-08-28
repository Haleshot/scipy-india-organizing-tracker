"""Where volunteer applications come from.

One interface, two implementations. Swapping the fixture for a Google Sheet
means changing ``VOLUNTEER_SOURCE`` and filling in the sheet id, not editing the
pipeline.

Privacy: a source may return contact details and the applicant's raw free-text
answers. Those fields ride into Neo4j, which is private infrastructure, and the
public snapshot exporter never reads them. Keep it that way; see
``scripts/export_public_snapshot.py``.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Protocol

from .models import APPLICATION_STATUSES, VolunteerApplicationRecord
from .workgroups import WorkgroupRegistry


class VolunteerApplicationSource(Protocol):
    """Yields volunteer applications, newest or oldest first, order not significant."""

    async def applications(self) -> list[VolunteerApplicationRecord]: ...


# ---------------------------------------------------------------------------
# Shared normalisation
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[str]:
    """Accept a list, or the comma/semicolon-separated string a spreadsheet gives you."""
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(v).strip() for v in value]
    else:
        items = [part.strip() for part in str(value).replace(";", ",").split(",")]
    return [i for i in items if i]


def _as_date(value: Any) -> datetime.date:
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return datetime.date.min


def normalize_record(
    raw: dict[str, Any], registry: WorkgroupRegistry
) -> VolunteerApplicationRecord:
    """Turn one source row into a record, resolving workgroup names to slugs.

    A preference that doesn't match the registry is dropped rather than guessed
    at, so an unmatched entry shows up as a volunteer with no interests instead
    of a wrong edge. Add an alias in ``config/workgroups.yaml`` to fix it.
    """
    status = str(raw.get("status") or "submitted").strip().lower().replace(" ", "_")
    if status not in APPLICATION_STATUSES:
        status = "submitted"

    def slugs(key: str) -> list[str]:
        resolved = [registry.resolve(item) for item in _as_list(raw.get(key))]
        return list(dict.fromkeys(s for s in resolved if s))

    return VolunteerApplicationRecord(
        application_id=str(raw["application_id"]).strip(),
        name=str(raw["name"]).strip(),
        preferred_workgroups=slugs("preferred_workgroups"),
        interests=_as_list(raw.get("interests")),
        skills=_as_list(raw.get("skills")),
        availability=str(raw.get("availability") or "").strip(),
        status=status,
        submitted_on=_as_date(raw.get("submitted_on")),
        assigned_workgroups=slugs("assigned_workgroups"),
        contact_email=str(raw.get("contact_email") or "").strip(),
        contact_phone=str(raw.get("contact_phone") or "").strip(),
        raw_response=str(raw.get("raw_response") or "").strip(),
    )


# ---------------------------------------------------------------------------
# Local JSON fixture
# ---------------------------------------------------------------------------


class JsonFileVolunteerSource:
    """Reads applications from a JSON file: ``{"applications": [ ... ]}``."""

    def __init__(self, path: Path, registry: WorkgroupRegistry) -> None:
        self._path = path
        self._registry = registry

    async def applications(self) -> list[VolunteerApplicationRecord]:
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        rows = payload["applications"] if isinstance(payload, dict) else payload
        return [normalize_record(row, self._registry) for row in rows]


# ---------------------------------------------------------------------------
# Google Sheet (form responses)
# ---------------------------------------------------------------------------

# Maps Google Form question text to record fields. Edit this when the form
# changes; nothing else needs to move.
SHEET_COLUMN_MAP = {
    "Timestamp": "submitted_on",
    "Your name": "name",
    "Email address": "contact_email",
    "Phone number": "contact_phone",
    "Which workgroups interest you?": "preferred_workgroups",
    "What are you interested in working on?": "interests",
    "Relevant skills": "skills",
    "When are you available?": "availability",
    "Anything else you'd like us to know?": "raw_response",
}


class GoogleSheetVolunteerSource:
    """Reads applications from the Sheet behind a Google Form.

    Not implemented yet, deliberately. Wiring it up needs three things, none of
    which we can check in:

    1. ``pip install google-api-python-client`` and read
       ``spreadsheets.values.get`` for ``VOLUNTEER_SHEET_ID`` /
       ``VOLUNTEER_SHEET_RANGE`` using the same service-account credential as
       the Drive source (``GOOGLE_SERVICE_ACCOUNT_CREDENTIAL``), with the
       ``spreadsheets.readonly`` scope added.
    2. The response sheet shared with that service account's email address.
    3. ``SHEET_COLUMN_MAP`` above updated to the real form's question text.

    Each row then goes through ``normalize_record`` exactly like a fixture row,
    with ``application_id`` derived from the row number if the form has no id
    column. Everything downstream is unchanged.
    """

    def __init__(self, sheet_id: str, sheet_range: str, registry: WorkgroupRegistry) -> None:
        self._sheet_id = sheet_id
        self._sheet_range = sheet_range
        self._registry = registry

    async def applications(self) -> list[VolunteerApplicationRecord]:
        raise NotImplementedError(
            "GoogleSheetVolunteerSource is a stub. See its docstring for the three "
            "steps to finish it, or keep VOLUNTEER_SOURCE=local for now."
        )

    def rows_to_records(
        self, header: list[str], rows: list[list[str]]
    ) -> list[VolunteerApplicationRecord]:
        """Row-to-record mapping, split out so it is testable without the API."""
        fields = [SHEET_COLUMN_MAP.get(column.strip(), "") for column in header]
        records = []
        for index, row in enumerate(rows, start=2):  # row 1 is the header
            raw: dict[str, Any] = {"application_id": f"ROW-{index}"}
            for field, value in zip(fields, row, strict=False):
                if field:
                    raw[field] = value
            if raw.get("name"):
                records.append(normalize_record(raw, self._registry))
        return records


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def volunteer_source(registry: WorkgroupRegistry) -> VolunteerApplicationSource:
    kind = os.environ.get("VOLUNTEER_SOURCE", "local").strip().lower()

    if kind == "local":
        path = Path(
            os.environ.get("VOLUNTEER_APPLICATIONS_FILE", "./data/volunteers/applications.json")
        )
        if not path.is_file():
            raise ValueError(f"VOLUNTEER_APPLICATIONS_FILE does not exist: {path.resolve()}")
        return JsonFileVolunteerSource(path, registry)

    if kind == "google_sheet":
        sheet_id = os.environ.get("VOLUNTEER_SHEET_ID", "").strip()
        if not sheet_id:
            raise ValueError("VOLUNTEER_SHEET_ID is required when VOLUNTEER_SOURCE=google_sheet.")
        sheet_range = os.environ.get("VOLUNTEER_SHEET_RANGE", "Form Responses 1")
        return GoogleSheetVolunteerSource(sheet_id, sheet_range, registry)

    if kind == "none":
        return _EmptyVolunteerSource()

    raise ValueError(f"Unknown VOLUNTEER_SOURCE={kind!r}. Use 'local', 'google_sheet' or 'none'.")


class _EmptyVolunteerSource:
    async def applications(self) -> list[VolunteerApplicationRecord]:
        return []
