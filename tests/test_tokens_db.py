"""Tests for `central_mcp.tokens_db` — SQLite token aggregation store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from central_mcp import tokens_db


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TestRecord:
    def test_inserts_row(self, fake_home: Path) -> None:
        tokens_db.record(
            ts=_now_utc_iso(), project="p", agent="claude",
            source="dispatch", dispatch_id="d1",
            input_tokens=100, output_tokens=50, total_tokens=150,
        )
        with tokens_db._connect() as conn:
            rows = conn.execute("SELECT * FROM usage").fetchall()
        assert len(rows) == 1
        assert rows[0]["total_tokens"] == 150
        assert rows[0]["source"] == "dispatch"

    def test_unique_constraint_dedups_orchestrator_turns(
        self, fake_home: Path
    ) -> None:
        for _ in range(3):
            tokens_db.record(
                ts=_now_utc_iso(), project="p", agent="claude",
                source="orchestrator", session_id="s1", request_id="r1",
                total_tokens=999,
            )
        with tokens_db._connect() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) AS n FROM usage"
            ).fetchone()
        assert rows["n"] == 1

    def test_never_raises_on_bad_input(self, fake_home: Path) -> None:
        # Source check constraint violation → swallowed, no exception.
        tokens_db.record(
            ts=_now_utc_iso(), project="p", agent="claude",
            source="bogus",
        )  # must not raise


class TestAggregation:
    def test_today_by_project_sums_matching_window(
        self, fake_home: Path
    ) -> None:
        ts = _now_utc_iso()
        tokens_db.record(ts=ts, project="p1", agent="claude",
                         source="dispatch", dispatch_id="a", total_tokens=100)
        tokens_db.record(ts=ts, project="p1", agent="claude",
                         source="dispatch", dispatch_id="b", total_tokens=250)
        tokens_db.record(ts=ts, project="p2", agent="codex",
                         source="dispatch", dispatch_id="c", total_tokens=77)
        result = tokens_db.today_by_project("UTC")
        assert result["p1"]["total"] == 350
        assert result["p2"]["total"] == 77

    def test_today_excludes_yesterday(self, fake_home: Path) -> None:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=2))
        tokens_db.record(
            ts=yesterday.isoformat(timespec="milliseconds"),
            project="p", agent="claude",
            source="dispatch", dispatch_id="old", total_tokens=9999,
        )
        tokens_db.record(
            ts=_now_utc_iso(),
            project="p", agent="claude",
            source="dispatch", dispatch_id="new", total_tokens=10,
        )
        today = tokens_db.today_by_project("UTC")
        assert today["p"]["total"] == 10      # yesterday excluded

    def test_week_includes_last_seven_days(self, fake_home: Path) -> None:
        two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
        tokens_db.record(
            ts=two_days_ago.isoformat(timespec="milliseconds"),
            project="p", agent="claude",
            source="dispatch", dispatch_id="mid", total_tokens=500,
        )
        tokens_db.record(
            ts=_now_utc_iso(),
            project="p", agent="claude",
            source="dispatch", dispatch_id="today", total_tokens=100,
        )
        week = tokens_db.week_by_project("UTC")
        assert week["p"]["total"] == 600      # both records in window

    def test_dispatch_and_orchestrator_accumulate_separately(
        self, fake_home: Path
    ) -> None:
        ts = _now_utc_iso()
        tokens_db.record(ts=ts, project="p", agent="claude",
                         source="dispatch", dispatch_id="d", total_tokens=200)
        tokens_db.record(ts=ts, project="p", agent="claude",
                         source="orchestrator", session_id="s", request_id="r",
                         total_tokens=800)
        today = tokens_db.today_by_project("UTC")
        assert today["p"]["dispatch"] == 200
        assert today["p"]["orchestrator"] == 800
        assert today["p"]["total"] == 1000

    def test_returns_empty_when_no_rows(self, fake_home: Path) -> None:
        assert tokens_db.today_by_project("UTC") == {}
        assert tokens_db.week_by_project("UTC") == {}

    def test_invalid_tz_falls_back_to_utc(self, fake_home: Path) -> None:
        tokens_db.record(
            ts=_now_utc_iso(), project="p", agent="claude",
            source="dispatch", dispatch_id="x", total_tokens=42,
        )
        # Malformed tz must not crash — returns aggregates as if UTC.
        result = tokens_db.today_by_project("Not/AReal_Zone")
        assert result["p"]["total"] == 42
