"""Tests for the `central-mcp monitor` curses dashboard logic.

Curses rendering is not tested (no TTY in CI); this exercises the non-UI
building blocks: timeline aggregation, quota cache thread-safety, and the
token_total helper.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from central_mcp import events, monitor


def _write_timeline(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class TestTokenTotal:
    def test_none_returns_zero(self) -> None:
        assert events.token_total(None) == 0

    def test_empty_dict_returns_zero(self) -> None:
        assert events.token_total({}) == 0

    def test_prefers_total_field(self) -> None:
        assert events.token_total({"total": 500, "input": 1, "output": 2}) == 500

    def test_falls_back_to_input_plus_output(self) -> None:
        assert events.token_total({"input": 300, "output": 200}) == 500

    def test_handles_string_numbers(self) -> None:
        assert events.token_total({"total": "123"}) == 123

    def test_garbage_values_return_zero(self) -> None:
        assert events.token_total({"input": "junk", "output": "x"}) == 0


class TestLoadTodayStats:
    def test_missing_timeline_returns_empty(self, fake_home: Path) -> None:
        assert monitor._load_today_stats() == {}

    def test_counts_dispatches_and_tokens_from_today(self, fake_home: Path) -> None:
        now = datetime.now(timezone.utc)
        today_mid = now.replace(hour=12, minute=0, second=0, microsecond=0)
        yesterday = today_mid - timedelta(days=1)
        path = events.timeline_path()
        _write_timeline(path, [
            # Yesterday — must be excluded
            {"ts": yesterday.isoformat(), "project": "p1", "event": "dispatched",
             "id": "old"},
            {"ts": yesterday.isoformat(), "project": "p1", "event": "complete",
             "id": "old", "ok": True, "agent": "claude",
             "tokens": {"total": 9999}},
            # Today
            {"ts": today_mid.isoformat(), "project": "p1", "event": "dispatched",
             "id": "a"},
            {"ts": today_mid.isoformat(), "project": "p1", "event": "complete",
             "id": "a", "ok": True, "agent": "claude",
             "tokens": {"total": 100}},
            {"ts": today_mid.isoformat(), "project": "p1", "event": "dispatched",
             "id": "b"},
            {"ts": today_mid.isoformat(), "project": "p1", "event": "complete",
             "id": "b", "ok": False, "agent": "claude",
             "tokens": {"input": 20, "output": 30}},
            {"ts": today_mid.isoformat(), "project": "p2", "event": "dispatched",
             "id": "c"},
        ])
        stats = monitor._load_today_stats()
        assert stats["p1"]["dispatches"] == 2
        assert stats["p1"]["tokens_total"] == 150
        assert stats["p1"]["agent"] == "claude"
        # last_ok is "most recent" under reverse iteration — b completed
        # after a, so last_ok should be False.
        assert stats["p1"]["last_ok"] is False
        assert stats["p2"]["dispatches"] == 1
        assert stats["p2"]["tokens_total"] == 0
        # Yesterday's 9999 tokens must not leak in
        assert "old" not in stats

    def test_skips_malformed_lines(self, fake_home: Path) -> None:
        now = datetime.now(timezone.utc).replace(hour=12)
        path = events.timeline_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "{ not json\n"
            + json.dumps({"ts": now.isoformat(), "project": "p", "event": "dispatched"})
            + "\n"
            + "also garbage\n",
            encoding="utf-8",
        )
        stats = monitor._load_today_stats()
        assert stats["p"]["dispatches"] == 1


class TestQuotaCache:
    def test_initial_state_needs_refresh(self) -> None:
        c = monitor._QuotaCache()
        assert c.needs_refresh() is True
        assert c.get() == {}
        assert c.fetched_at() == 0.0
        assert c.is_fetching() is False

    def test_begin_fetch_prevents_concurrent_refresh(self) -> None:
        c = monitor._QuotaCache()
        c.begin_fetch()
        # While a fetch is in-flight, needs_refresh must be False so we
        # don't spawn a second thread.
        assert c.needs_refresh() is False
        assert c.is_fetching() is True

    def test_set_clears_fetching_flag(self) -> None:
        c = monitor._QuotaCache()
        c.begin_fetch()
        c.set({"claude": {"mode": "api_key"}})
        assert c.is_fetching() is False
        assert c.get() == {"claude": {"mode": "api_key"}}
        assert c.fetched_at() > 0

    def test_mark_fetched_preserves_prior_data(self) -> None:
        c = monitor._QuotaCache()
        c.set({"claude": {"mode": "pro", "raw": {"x": 1}}})
        before = c.get()
        c.begin_fetch()
        c.mark_fetched()  # simulates a failed refresh
        assert c.get() == before
        assert c.is_fetching() is False

    def test_abort_fetch_releases_flag_without_setting_data(self) -> None:
        c = monitor._QuotaCache()
        c.begin_fetch()
        c.abort_fetch()
        assert c.is_fetching() is False
        assert c.get() == {}

    def test_get_returns_shallow_copy(self) -> None:
        c = monitor._QuotaCache()
        c.set({"claude": {"mode": "api_key"}})
        snapshot = c.get()
        snapshot["claude"] = {"mode": "tampered"}
        # Mutating the returned dict must not affect the cache.
        assert c.get() == {"claude": {"mode": "api_key"}}

    def test_concurrent_set_and_get_do_not_deadlock(self) -> None:
        c = monitor._QuotaCache()
        stop = threading.Event()

        def writer():
            while not stop.is_set():
                c.set({"claude": {"mode": "api_key"}})

        def reader():
            while not stop.is_set():
                c.get()

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        stop.wait(0.1)  # let them race briefly
        stop.set()
        for t in threads:
            t.join(timeout=1.0)
            assert not t.is_alive()
