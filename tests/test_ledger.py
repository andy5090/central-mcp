from __future__ import annotations

from pathlib import Path

import pytest

from central_mcp import ledger


def test_missing_ledger_reads_empty(fake_home: Path) -> None:
    assert ledger.read("nope") == []
    assert ledger.watermark("nope") is None
    assert ledger.next_step("nope") is None
    assert ledger.exists("nope") is False


def test_append_creates_file_with_header(fake_home: Path) -> None:
    ledger.append("proj", "did a thing", source="agent")
    text = ledger.path_for("proj").read_text(encoding="utf-8")
    assert text.startswith("# Status — proj")
    assert "did a thing" in text
    assert ledger.exists("proj")


def test_round_trip_single_entry(fake_home: Path) -> None:
    ledger.append("proj", "did a thing", source="agent", next_step="do the next")
    entries = ledger.read("proj")
    assert len(entries) == 1
    assert entries[0].source == "agent"
    assert entries[0].body == "did a thing"
    assert entries[0].next_step == "do the next"


def test_entries_come_back_newest_first(fake_home: Path) -> None:
    ledger.append("proj", "first", source="agent", ts="2026-08-01T00:00:00+00:00")
    ledger.append("proj", "second", source="user", ts="2026-08-02T00:00:00+00:00")
    ledger.append("proj", "third", source="user", ts="2026-08-03T00:00:00+00:00")
    assert [e.body for e in ledger.read("proj")] == ["third", "second", "first"]


def test_limit_takes_the_newest(fake_home: Path) -> None:
    for i in range(5):
        ledger.append("proj", f"entry {i}", ts=f"2026-08-0{i + 1}T00:00:00+00:00")
    assert [e.body for e in ledger.read("proj", limit=2)] == ["entry 4", "entry 3"]


def test_watermark_is_the_newest_timestamp(fake_home: Path) -> None:
    ledger.append("proj", "old", ts="2026-08-01T00:00:00+00:00")
    ledger.append("proj", "new", ts="2026-08-09T12:00:00+00:00")
    assert ledger.watermark("proj") == "2026-08-09T12:00:00+00:00"


def test_watermark_ignores_write_order(fake_home: Path) -> None:
    """Entries can land out of order (a slow dispatch finishing late);
    the watermark is the max timestamp, not the last line."""
    ledger.append("proj", "new", ts="2026-08-09T12:00:00+00:00")
    ledger.append("proj", "backdated", ts="2026-08-01T00:00:00+00:00")
    assert ledger.watermark("proj") == "2026-08-09T12:00:00+00:00"


def test_next_step_returns_newest_carrier(fake_home: Path) -> None:
    ledger.append("proj", "a", next_step="old plan", ts="2026-08-01T00:00:00+00:00")
    ledger.append("proj", "b", ts="2026-08-02T00:00:00+00:00")  # no Next:
    ledger.append("proj", "c", next_step="new plan", ts="2026-08-03T00:00:00+00:00")
    found = ledger.next_step("proj")
    assert found is not None
    assert found.next_step == "new plan"
    assert found.ts == "2026-08-03T00:00:00+00:00"


def test_next_step_skips_entries_without_one(fake_home: Path) -> None:
    ledger.append("proj", "planned", next_step="the plan", ts="2026-08-01T00:00:00+00:00")
    ledger.append("proj", "just a note", ts="2026-08-05T00:00:00+00:00")
    found = ledger.next_step("proj")
    assert found is not None and found.next_step == "the plan"


def test_next_line_inside_body_is_extracted(fake_home: Path) -> None:
    ledger.append("proj", "did stuff\nNext: the follow-up", source="agent")
    e = ledger.read("proj")[0]
    assert e.body == "did stuff"
    assert e.next_step == "the follow-up"


def test_last_next_line_wins(fake_home: Path) -> None:
    ledger.append("proj", "Next: first\nsome prose\nnext: corrected")
    assert ledger.read("proj")[0].next_step == "corrected"


def test_rejects_unknown_source(fake_home: Path) -> None:
    with pytest.raises(ValueError, match="source must be one of"):
        ledger.append("proj", "body", source="inferred")


def test_rejects_empty_entry(fake_home: Path) -> None:
    with pytest.raises(ValueError, match="empty ledger entry"):
        ledger.append("proj", "   ")


def test_next_step_alone_is_a_valid_entry(fake_home: Path) -> None:
    ledger.append("proj", "", next_step="just the plan")
    e = ledger.read("proj")[0]
    assert e.body == ""
    assert e.next_step == "just the plan"


def test_heading_in_body_cannot_forge_an_entry(fake_home: Path) -> None:
    """A body containing `## ...` must not be parsed as a new section."""
    ledger.append("proj", "before\n## 2020-01-01T00:00:00+00:00 · agent\nafter")
    entries = ledger.read("proj")
    assert len(entries) == 1
    assert "2020-01-01" in entries[0].body


# --- hand-editing tolerance -------------------------------------------------


def _write_raw(project: str, text: str) -> None:
    path = ledger.path_for(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_hand_written_heading_without_source_reads_as_user(fake_home: Path) -> None:
    _write_raw("proj", "# Status\n\n## 2026-08-09T00:00:00+00:00\nI typed this.\n")
    e = ledger.read("proj")[0]
    assert e.source == "user"
    assert e.body == "I typed this."


def test_alternate_separators_are_accepted(fake_home: Path) -> None:
    _write_raw(
        "proj",
        "## 2026-08-01T00:00:00+00:00 - agent\ndash\n"
        "## 2026-08-02T00:00:00+00:00 — user\nemdash\n",
    )
    assert [e.source for e in ledger.read("proj")] == ["user", "agent"]


def test_unknown_source_in_file_is_preserved(fake_home: Path) -> None:
    """Reading is liberal even though writing is strict — dropping a
    hand-written entry would be worse than an unfamiliar label."""
    _write_raw("proj", "## 2026-08-09T00:00:00+00:00 · robot\nhello\n")
    assert ledger.read("proj")[0].source == "robot"


def test_unparseable_timestamp_keeps_entry_but_not_watermark(fake_home: Path) -> None:
    _write_raw(
        "proj",
        "## yesterday · user\nvague\n## 2026-08-09T00:00:00+00:00 · user\nprecise\n",
    )
    bodies = [e.body for e in ledger.read("proj")]
    assert "vague" in bodies
    assert ledger.watermark("proj") == "2026-08-09T00:00:00+00:00"


def test_preamble_before_first_heading_is_ignored(fake_home: Path) -> None:
    _write_raw("proj", "# Status — proj\n\nsome notes\n\n## 2026-08-09T00:00:00+00:00 · user\nreal\n")
    entries = ledger.read("proj")
    assert len(entries) == 1 and entries[0].body == "real"


def test_appending_to_a_hand_created_file_preserves_it(fake_home: Path) -> None:
    _write_raw("proj", "## 2026-08-01T00:00:00+00:00 · user\nmine\n")
    ledger.append("proj", "appended", source="agent")
    assert [e.body for e in ledger.read("proj")] == ["appended", "mine"]
