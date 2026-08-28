import datetime
from pathlib import Path

import pytest

from scipy_india_kg.volunteers import (
    GoogleSheetVolunteerSource,
    JsonFileVolunteerSource,
    normalize_record,
)

FIXTURE = Path(__file__).resolve().parent.parent / "data" / "volunteers" / "applications.json"


async def test_fixture_loads(registry):
    applications = await JsonFileVolunteerSource(FIXTURE, registry).applications()
    assert len(applications) == 10
    priya = next(a for a in applications if a.name == "Priya Vasudevan")
    assert priya.preferred_workgroups == ["volunteers", "coc-inclusion"]
    assert priya.status == "assigned"
    assert priya.submitted_on == datetime.date(2026, 2, 14)


async def test_fixture_contact_details_are_obviously_fake(registry):
    applications = await JsonFileVolunteerSource(FIXTURE, registry).applications()
    assert all(a.contact_email.endswith("@example.invalid") for a in applications)
    assert all("00000-" in a.contact_phone for a in applications)


def test_comma_separated_strings_work_like_lists(registry):
    record = normalize_record(
        {
            "application_id": "ROW-2",
            "name": "Test Person",
            "preferred_workgroups": "Design, Communications",
            "skills": "Figma; Python",
        },
        registry,
    )
    assert record.preferred_workgroups == ["design-branding", "communications"]
    assert record.skills == ["Figma", "Python"]


def test_unknown_workgroup_preference_is_dropped(registry):
    record = normalize_record(
        {"application_id": "X", "name": "T", "preferred_workgroups": "Quidditch"}, registry
    )
    assert record.preferred_workgroups == []


def test_unknown_status_falls_back_to_submitted(registry):
    record = normalize_record({"application_id": "X", "name": "T", "status": "maybe"}, registry)
    assert record.status == "submitted"


def test_sheet_rows_map_through_the_column_map(registry):
    source = GoogleSheetVolunteerSource("sheet", "Form Responses 1", registry)
    records = source.rows_to_records(
        ["Timestamp", "Your name", "Email address", "Which workgroups interest you?"],
        [["2026-03-01 10:00:00", "Asha Kumar", "asha@example.invalid", "Sponsorship"]],
    )
    assert len(records) == 1
    assert records[0].name == "Asha Kumar"
    assert records[0].preferred_workgroups == ["sponsorship"]
    assert records[0].submitted_on == datetime.date(2026, 3, 1)


async def test_google_sheet_source_is_honest_about_being_a_stub(registry):
    source = GoogleSheetVolunteerSource("sheet", "range", registry)
    with pytest.raises(NotImplementedError):
        await source.applications()
