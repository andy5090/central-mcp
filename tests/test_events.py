"""Tests for the dispatch event log (central_mcp.events).

Verifies that log_event:
  - creates ~/.central-mcp/logs/<project>/dispatch.jsonl if missing,
  - appends one JSON object per call with the required fields,
  - never raises, even under failure conditions.
"""

from __future__ import annotations

import json
from pathlib import Path

from central_mcp import events


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


class TestLogEvent:
    def test_creates_log_file_on_first_call(self, fake_home: Path) -> None:
        events.log_event("alpha", "abc123", "start", agent="claude", prompt="hi")
        log = events.log_path("alpha")
        assert log.exists()
        records = _read_jsonl(log)
        assert len(records) == 1
        r = records[0]
        assert r["id"] == "abc123"
        assert r["event"] == "start"
        assert r["agent"] == "claude"
        assert r["prompt"] == "hi"
        assert "ts" in r

    def test_appends_multiple_events_in_order(self, fake_home: Path) -> None:
        events.log_event("alpha", "id1", "start", prompt="do x")
        events.log_event("alpha", "id1", "output", stream="stdout", chunk="working...")
        events.log_event("alpha", "id1", "complete", ok=True, exit_code=0)

        records = _read_jsonl(events.log_path("alpha"))
        assert [r["event"] for r in records] == ["start", "output", "complete"]
        assert all(r["id"] == "id1" for r in records)

    def test_per_project_isolation(self, fake_home: Path) -> None:
        events.log_event("alpha", "a1", "start", prompt="x")
        events.log_event("beta", "b1", "start", prompt="y")

        alpha_records = _read_jsonl(events.log_path("alpha"))
        beta_records = _read_jsonl(events.log_path("beta"))

        assert len(alpha_records) == 1
        assert len(beta_records) == 1
        assert alpha_records[0]["id"] == "a1"
        assert beta_records[0]["id"] == "b1"

    def test_swallows_errors_never_raises(
        self, fake_home: Path, monkeypatch
    ) -> None:
        # Force log_dir to a path we can't write to; log_event must not propagate.
        def _boom(*a, **k):
            raise OSError("no disk space")

        monkeypatch.setattr(events, "log_dir", _boom)
        # Should return None without raising.
        assert events.log_event("alpha", "id", "start") is None

    def test_timestamp_format_is_iso_with_millis(self, fake_home: Path) -> None:
        events.log_event("alpha", "id", "start")
        records = _read_jsonl(events.log_path("alpha"))
        ts = records[0]["ts"]
        # ISO 8601 with millisecond precision, e.g. 2026-04-18T05:12:34.567+00:00
        assert "T" in ts
        assert "." in ts  # millisecond separator


class TestLogTimelineConcurrency:
    """Guard against the original race that prompted the flock/Lock fix.

    Without locking, ts-generation and file write are separated by a
    thread-schedulable gap, so the file's line order can diverge from
    ts order. Monitor's reverse-scan `break-at-midnight` optimization
    relies on the invariant that file order matches ts order.
    """

    def test_file_order_matches_ts_order_under_contention(
        self, fake_home: Path
    ) -> None:
        import threading as _th

        n_threads, n_per = 10, 50
        tag = "concurrency-test"     # filter key: leaked writes from daemon
                                     # threads in earlier dispatch tests may
                                     # share the same timeline file.
        errors: list[BaseException] = []

        def writer() -> None:
            try:
                for _ in range(n_per):
                    events.log_timeline("d", tag, "dispatched")
            except BaseException as e:   # pragma: no cover
                errors.append(e)

        threads = [_th.Thread(target=writer) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        assert all(not t.is_alive() for t in threads)

        records = [
            r for r in _read_jsonl(events.timeline_path())
            if r.get("project") == tag
        ]
        assert len(records) == n_threads * n_per

        ts_list = [r["ts"] for r in records]
        # File order must equal ts order (non-decreasing).
        assert ts_list == sorted(ts_list), (
            "timeline.jsonl line order diverged from ts order — "
            "locking regression in log_timeline"
        )

    def test_single_write_is_one_full_line(self, fake_home: Path) -> None:
        tag = "single-write-test"
        events.log_timeline("d", tag, "dispatched", extra="x")
        text = events.timeline_path().read_text()
        assert text.endswith("\n")
        mine = [
            r for r in _read_jsonl(events.timeline_path())
            if r.get("project") == tag
        ]
        assert len(mine) == 1
        assert mine[0]["event"] == "dispatched"
        assert mine[0]["extra"] == "x"
