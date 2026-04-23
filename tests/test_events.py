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


class TestTimelineRotation:
    """Rotation lifts a full `timeline.jsonl` into `archive/` alongside a
    compact summary JSON. Thresholds are module-level so tests monkeypatch
    them down instead of having to generate megabytes of data.
    """

    def test_maybe_rotate_noop_below_threshold(self, fake_home: Path) -> None:
        events.log_timeline("d", "proj", "dispatched")
        assert events.timeline_path().exists()
        # archive dir should not be created yet
        assert not events.archive_dir().exists() or not list(events.archive_dir().iterdir())

    def test_rotates_when_size_threshold_crossed(
        self, fake_home: Path, monkeypatch
    ) -> None:
        # Drop the byte threshold so the first few writes trigger rotate.
        monkeypatch.setattr(events, "_ROTATE_BYTES", 100)
        for i in range(5):
            events.log_timeline(f"d{i}", "proj", "dispatched")
        archives = events.list_archives()
        assert len(archives) >= 1, "rotation should have created an archive"
        # Paired summary exists
        summary = events.read_archive_summary(archives[0])
        assert summary is not None
        assert summary["record_count"] >= 1
        assert "proj" in summary["per_project"]

    def test_summary_contains_event_counts(
        self, fake_home: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(events, "_ROTATE_BYTES", 50)
        # Mix of events.
        events.log_timeline("d1", "p1", "dispatched", agent="claude")
        events.log_timeline("d1", "p1", "complete", ok=True, agent="claude")
        events.log_timeline("d2", "p1", "dispatched", agent="claude")
        events.log_timeline("d2", "p1", "complete", ok=False, agent="claude")
        events.log_timeline("d3", "p2", "cancelled", agent="codex")
        archives = events.list_archives()
        assert archives
        summary = events.read_archive_summary(archives[-1])  # oldest
        # Records accumulate across rotations; confirm agent tally is present.
        combined = {"p1": {"dispatched": 0, "succeeded": 0, "failed": 0, "cancelled": 0},
                    "p2": {"dispatched": 0, "succeeded": 0, "failed": 0, "cancelled": 0}}
        for a in archives:
            s = events.read_archive_summary(a)
            if s is None:
                continue
            for proj, d in s["per_project"].items():
                for k, v in d.items():
                    combined[proj][k] += v
        assert combined["p1"]["succeeded"] + combined["p1"]["failed"] >= 2
        assert combined["p2"]["cancelled"] >= 1

    def test_list_archives_empty_when_no_rotate(self, fake_home: Path) -> None:
        assert events.list_archives() == []

    def test_read_archive_summary_returns_none_for_missing(
        self, fake_home: Path
    ) -> None:
        assert events.read_archive_summary(Path("/nonexistent.jsonl")) is None


class TestOrchestrationHistoryArchives:
    """Integration: `orchestration_history(include_archives=True)` surfaces
    archive summaries without reading raw rotated records.
    """

    def test_no_archives_section_by_default(self, fake_home: Path) -> None:
        from central_mcp import server
        r = server.orchestration_history()
        assert "archived_summaries" not in r

    def test_include_archives_empty_when_none_exist(
        self, fake_home: Path
    ) -> None:
        from central_mcp import server
        r = server.orchestration_history(include_archives=True)
        assert r["archived_summaries"] == []

    def test_include_archives_returns_summaries(
        self, fake_home: Path, monkeypatch
    ) -> None:
        from central_mcp import server
        monkeypatch.setattr(events, "_ROTATE_BYTES", 80)

        for i in range(5):
            events.log_timeline(f"d{i}", "proj", "dispatched")

        r = server.orchestration_history(include_archives=True)
        assert len(r["archived_summaries"]) >= 1
        first = r["archived_summaries"][0]
        assert first["file"].startswith("timeline-")
        assert first["file"].endswith(".jsonl")
        assert "per_project" in first
        assert "covers" in first


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
