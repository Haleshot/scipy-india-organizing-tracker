import datetime

from scipy_india_kg.extraction import extract_meeting_markdown, split_meetings


def meetings(notes_text, registry):
    parsed = [extract_meeting_markdown(s, registry) for s in split_meetings(notes_text)]
    return [m for m in parsed if m is not None]


def test_split_finds_top_level_sections_only(notes_text):
    sections = split_meetings(notes_text)
    # `### Decisions` and friends stay inside their meeting.
    assert all("### Decisions" not in s.splitlines()[0] for s in sections)
    assert sum(1 for s in sections if s.splitlines()[0].startswith("Meeting: 2026-")) == 5


def test_sections_without_a_date_are_skipped(registry):
    assert (
        extract_meeting_markdown("Key links\n\n* Website: https://example.invalid", registry)
        is None
    )


def test_meeting_header_fields(notes_text, registry):
    first = meetings(notes_text, registry)[0]
    assert first.date == datetime.date(2026, 1, 9)
    assert first.title == "Kickoff"
    assert first.organizer.name == "Meera Raghavan"
    assert [p.name for p in first.attendees] == [
        "Devika Nair",
        "Arjun Pillai",
        "Nikhil Bose",
        "Farida Qureshi",
    ]
    assert "Meera Raghavan" not in [p.name for p in first.attendees]


def test_task_owner_workgroup_status_and_due(notes_text, registry):
    tasks = {t.description: t for t in meetings(notes_text, registry)[0].tasks}
    cfp = tasks["Draft the CFP timeline and circulate it to the organizing list"]
    assert [o.name for o in cfp.owners] == ["Devika Nair"]
    assert cfp.workgroup == "program"
    assert cfp.status == "open"
    assert cfp.due == "23 Jan"


def test_a_task_without_an_owner_stays_unowned(notes_text, registry):
    tasks = {t.description: t for t in meetings(notes_text, registry)[0].tasks}
    assert tasks["Collect quotes from three candidate venues"].owners == []


def test_explicit_status_overrides_the_checkbox(notes_text, registry):
    tasks = {t.description: t for t in meetings(notes_text, registry)[0].tasks}
    assert tasks["Set up the shared Drive folder and the meeting-notes doc"].status == "done"


def test_status_changes_across_meetings(notes_text, registry):
    statuses = [
        (m.date, t.status)
        for m in meetings(notes_text, registry)
        for t in m.tasks
        if t.description == "Port the 2025 site template and put up a holding page"
    ]
    assert [s for _, s in statuses] == ["open", "blocked", "in_progress"]


def test_decisions_carry_their_workgroup(notes_text, registry):
    first = meetings(notes_text, registry)[0]
    tagged = {d.workgroup for d in first.decisions}
    assert "program" in tagged and "finance" in tagged
    # A decision with no workgroup prefix stays untagged rather than guessed.
    assert None in tagged


def test_workgroup_moves(notes_text, registry):
    first = meetings(notes_text, registry)[0]
    assert ("Devika Nair", "program") in [
        (m.person.name, m.workgroup) for m in first.workgroup_moves
    ]


def test_unknown_status_word_falls_back_to_unknown(registry):
    section = "2026-04-01 — Test\n\n### Action items\n- Something — status: probably-fine\n"
    meeting = extract_meeting_markdown(section, registry)
    assert meeting.tasks[0].status == "unknown"


def test_unknown_workgroup_is_dropped_not_invented(registry):
    section = "2026-04-01 — Test\n\n### Action items\n- Something — workgroup: hackathon\n"
    meeting = extract_meeting_markdown(section, registry)
    assert meeting.tasks[0].workgroup is None
