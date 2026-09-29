"""Tests for mid-run dispatch visibility: `events.tail_output`, the
`tail_dispatch` MCP tool, the progress columns in `dispatches.db`, and
`pulse.output_health`.

Two properties matter most here. A tail must never repeat or drop a line,
including lines that share one millisecond. And silence must be read
according to the agent: an agent that prints only on exit is not stuck
because it is quiet.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from central_mcp import dispatches_db, events, pulse, registry, server
from central_mcp.adapters.base import Adapter


# ---------- helpers ----------

def _write_log(project: str, records: list[dict]) -> Path:
    path = events.log_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _out(ts: str, dispatch_id: str, chunk: str, stream: str = "stdout") -> dict:
    return {
        "ts": ts, "id": dispatch_id, "event": "output",
        "agent": "stub", "stream": stream, "chunk": chunk,
    }


def _ts(sec: int, ms: int = 0) -> str:
    base = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=sec, milliseconds=ms)).isoformat(
        timespec="milliseconds"
    )


# ---------- events.tail_output ----------

class TestTailOutput:
    def test_missing_log_is_empty(self, fake_home: Path) -> None:
        r = events.tail_output("nope", "abc")
        assert r == {"lines": [], "skipped": 0, "next_since": None}

    def test_returns_lines_oldest_first(self, fake_home: Path) -> None:
        _write_log("p", [_out(_ts(i), "d1", f"line {i}") for i in range(3)])
        r = events.tail_output("p", "d1")
        assert [l["text"] for l in r["lines"]] == ["line 0", "line 1", "line 2"]

    def test_other_dispatches_are_excluded(self, fake_home: Path) -> None:
        _write_log("p", [
            _out(_ts(0), "d1", "mine"),
            _out(_ts(1), "d2", "theirs"),
            _out(_ts(2), "d1", "mine too"),
        ])
        r = events.tail_output("p", "d1")
        assert [l["text"] for l in r["lines"]] == ["mine", "mine too"]

    def test_non_output_events_are_excluded(self, fake_home: Path) -> None:
        _write_log("p", [
            {"ts": _ts(0), "id": "d1", "event": "start", "prompt": "x"},
            _out(_ts(1), "d1", "real output"),
            {"ts": _ts(2), "id": "d1", "event": "complete", "ok": True},
        ])
        r = events.tail_output("p", "d1")
        assert [l["text"] for l in r["lines"]] == ["real output"]

    def test_cursor_returns_only_newer_lines(self, fake_home: Path) -> None:
        _write_log("p", [_out(_ts(i), "d1", f"line {i}") for i in range(3)])
        first = events.tail_output("p", "d1")
        _write_log("p", [_out(_ts(3), "d1", "line 3")])
        second = events.tail_output("p", "d1", since=first["next_since"])
        assert [l["text"] for l in second["lines"]] == ["line 3"]

    def test_no_new_output_returns_nothing_and_a_usable_cursor(
        self, fake_home: Path
    ) -> None:
        _write_log("p", [_out(_ts(0), "d1", "only")])
        first = events.tail_output("p", "d1")
        again = events.tail_output("p", "d1", since=first["next_since"])
        assert again["lines"] == []
        later = events.tail_output("p", "d1", since=again["next_since"])
        assert later["lines"] == []

    def test_lines_sharing_a_millisecond_are_neither_repeated_nor_dropped(
        self, fake_home: Path
    ) -> None:
        """Output arrives in bursts. A read that lands between two lines
        with one timestamp must deliver the second on the next call."""
        same = _ts(5, 123)
        _write_log("p", [_out(same, "d1", "a"), _out(same, "d1", "b")])
        first = events.tail_output("p", "d1")
        assert [l["text"] for l in first["lines"]] == ["a", "b"]

        _write_log("p", [_out(same, "d1", "c"), _out(_ts(6), "d1", "d")])
        second = events.tail_output("p", "d1", since=first["next_since"])
        assert [l["text"] for l in second["lines"]] == ["c", "d"]

    def test_plain_timestamp_means_strictly_after(self, fake_home: Path) -> None:
        _write_log("p", [_out(_ts(i), "d1", f"line {i}") for i in range(3)])
        r = events.tail_output("p", "d1", since=_ts(1))
        assert [l["text"] for l in r["lines"]] == ["line 2"]

    def test_max_lines_keeps_the_newest_and_counts_the_rest(
        self, fake_home: Path
    ) -> None:
        _write_log("p", [_out(_ts(i), "d1", f"line {i}") for i in range(10)])
        r = events.tail_output("p", "d1", max_lines=3)
        assert [l["text"] for l in r["lines"]] == ["line 7", "line 8", "line 9"]
        assert r["skipped"] == 7

    def test_skipped_lines_are_not_delivered_later(self, fake_home: Path) -> None:
        """The cursor moves past skipped lines: a tail shows the present,
        it does not replay a backlog."""
        _write_log("p", [_out(_ts(i), "d1", f"line {i}") for i in range(10)])
        first = events.tail_output("p", "d1", max_lines=3)
        second = events.tail_output("p", "d1", since=first["next_since"])
        assert second["lines"] == []

    def test_long_chunk_is_cut_and_flagged(self, fake_home: Path) -> None:
        _write_log("p", [_out(_ts(0), "d1", "x" * 5000)])
        line = events.tail_output("p", "d1", max_chunk_chars=100)["lines"][0]
        assert len(line["text"]) == 100
        assert line["truncated"] is True

    def test_not_before_bounds_the_first_read(self, fake_home: Path) -> None:
        """An id seen long before the dispatch started is not this dispatch."""
        _write_log("p", [
            _out(_ts(0), "d1", "ancient"),
            _out(_ts(1000), "d1", "current"),
        ])
        start = datetime(2026, 9, 1, 12, 16, 0, tzinfo=timezone.utc)
        r = events.tail_output("p", "d1", not_before=start)
        assert [l["text"] for l in r["lines"]] == ["current"]

    def test_half_written_final_line_is_skipped_then_delivered(
        self, fake_home: Path
    ) -> None:
        path = _write_log("p", [_out(_ts(0), "d1", "whole")])
        full = json.dumps(_out(_ts(1), "d1", "arriving"))
        with path.open("a") as f:
            f.write(full[:40])
        first = events.tail_output("p", "d1")
        assert [l["text"] for l in first["lines"]] == ["whole"]

        with path.open("a") as f:
            f.write(full[40:] + "\n")
        second = events.tail_output("p", "d1", since=first["next_since"])
        assert [l["text"] for l in second["lines"]] == ["arriving"]

    def test_reads_across_block_boundaries(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A line split across two read blocks must come back whole."""
        monkeypatch.setattr(events, "_TAIL_BLOCK", 64)
        _write_log("p", [_out(_ts(i), "d1", f"line {i} " + "y" * 50) for i in range(6)])
        r = events.tail_output("p", "d1")
        assert [l["text"][:6] for l in r["lines"]] == [f"line {i}" for i in range(6)]

    def test_non_ascii_output_survives(self, fake_home: Path) -> None:
        _write_log("p", [_out(_ts(0), "d1", "테스트 통과 ✓")])
        assert events.tail_output("p", "d1")["lines"][0]["text"] == "테스트 통과 ✓"

    def test_stream_label_is_kept(self, fake_home: Path) -> None:
        _write_log("p", [_out(_ts(0), "d1", "warn", stream="stderr")])
        assert events.tail_output("p", "d1")["lines"][0]["stream"] == "stderr"


class TestParseCursor:
    def test_empty(self) -> None:
        assert events.parse_cursor(None) == (None, 0)

    def test_cursor_with_count(self) -> None:
        ts, n = events.parse_cursor(f"{_ts(1)}#4")
        assert ts is not None and n == 4

    def test_plain_timestamp_has_no_count(self) -> None:
        ts, n = events.parse_cursor(_ts(1))
        assert ts is not None and n is None

    def test_garbage_reads_as_no_cursor(self) -> None:
        assert events.parse_cursor("not a time") == (None, 0)


# ---------- pulse.output_health ----------

class TestOutputHealth:
    now = datetime(2026, 9, 1, 13, 0, 0, tzinfo=timezone.utc)

    def _progress(self, age_sec: float, lines: int = 5) -> dict:
        at = (self.now - timedelta(seconds=age_sec)).isoformat(timespec="milliseconds")
        return {"last_output_at": at, "output_lines": lines, "output_bytes": 100}

    def test_recent_output_is_streaming(self) -> None:
        h = pulse.output_health(self._progress(30), "codex", now=self.now)
        assert h["state"] == "streaming"

    def test_long_silence_after_output_is_quiet(self) -> None:
        h = pulse.output_health(self._progress(20 * 60), "codex", now=self.now)
        assert h["state"] == "quiet"

    def test_silence_seen_in_healthy_dispatches_is_not_quiet(self) -> None:
        """660s is the longest silence observed in a dispatch that then
        succeeded; the threshold must sit above it."""
        h = pulse.output_health(self._progress(660), "opencode", now=self.now)
        assert h["state"] == "streaming"

    def test_exit_only_agent_with_no_output_is_not_flagged(self) -> None:
        h = pulse.output_health({"output_lines": 0}, "claude", now=self.now)
        assert h["state"] == "exit_only"
        assert h["streams_output"] is False

    def test_streaming_agent_with_no_output(self) -> None:
        h = pulse.output_health({"output_lines": 0}, "codex", now=self.now)
        assert h["state"] == "no_output_yet"

    def test_unmeasured_agent_is_not_judged(self) -> None:
        h = pulse.output_health({"output_lines": 0}, "droid", now=self.now)
        assert h["state"] == "no_output_yet"
        assert h["streams_output"] is None

    def test_unknown_agent_does_not_raise(self) -> None:
        h = pulse.output_health(None, "no-such-agent", now=self.now)
        assert h["state"] == "no_output_yet"

    def test_exit_only_agent_that_did_print_is_judged_by_its_output(self) -> None:
        """The flag describes the usual case; actual output outranks it."""
        h = pulse.output_health(self._progress(10), "claude", now=self.now)
        assert h["state"] == "streaming"


# ---------- dispatches_db progress columns ----------

class TestProgressColumns:
    def _start(self, dispatch_id: str = "d1") -> None:
        dispatches_db.upsert_started({
            "id": dispatch_id, "project": "p", "agent": "stub",
            "status": "running", "started": time.time(), "prompt": "x",
        })

    def test_new_dispatch_has_zeroed_progress(self, fake_home: Path) -> None:
        self._start()
        progress = dispatches_db.get("d1")["progress"]
        assert progress["output_lines"] == 0
        assert progress["last_output_at"] is None

    def test_record_progress_round_trip(self, fake_home: Path) -> None:
        self._start()
        dispatches_db.record_progress(
            "d1", last_output_at=_ts(5), output_lines=12,
            output_bytes=340, attempt_count=2,
        )
        assert dispatches_db.get("d1")["progress"] == {
            "last_output_at": _ts(5), "output_lines": 12,
            "output_bytes": 340, "attempt_count": 2,
        }

    def test_record_progress_on_unknown_id_is_harmless(self, fake_home: Path) -> None:
        dispatches_db.record_progress(
            "ghost", last_output_at=None, output_lines=1,
            output_bytes=1, attempt_count=1,
        )
        assert dispatches_db.get("ghost") is None

    def test_database_from_an_older_version_is_migrated(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A db created before the progress columns existed must gain them
        and keep its rows."""
        path = dispatches_db.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.execute(
            """CREATE TABLE dispatches (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, agent TEXT,
                status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, duration_sec REAL, exit_code INTEGER,
                ok INTEGER, fallback_used INTEGER DEFAULT 0,
                prompt_preview TEXT, command TEXT, output TEXT, stderr TEXT,
                error TEXT, tokens_json TEXT, chain_json TEXT,
                updated_at TEXT NOT NULL)"""
        )
        conn.execute(
            "INSERT INTO dispatches (id, project, status, started_at, updated_at) "
            "VALUES ('old', 'p', 'running', ?, ?)", (_ts(0), _ts(0)),
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(dispatches_db, "_migrated", set())

        entry = dispatches_db.get("old")
        assert entry is not None
        assert entry["progress"]["output_lines"] == 0
        dispatches_db.record_progress(
            "old", last_output_at=_ts(1), output_lines=3,
            output_bytes=9, attempt_count=1,
        )
        assert dispatches_db.get("old")["progress"]["output_lines"] == 3


# ---------- end to end: a real subprocess ----------

class _StubAdapter(Adapter):
    def __init__(self, name: str, argv_fn, streams: bool | None = None):
        super().__init__(name=name, launch=(), streams_output=streams)
        self._argv_fn = argv_fn

    def exec_argv(self, prompt, *, resume=True, permission_mode="restricted", session_id=None):
        return self._argv_fn(prompt)


@pytest.fixture
def stub_project(fake_home: Path, tmp_path: Path) -> str:
    cwd = tmp_path / "stub-cwd"
    cwd.mkdir()
    registry.add_project(name="stubproj", path_=str(cwd), agent="stub")
    return "stubproj"


def _install(monkeypatch: pytest.MonkeyPatch, script: str, streams: bool | None = True) -> None:
    from central_mcp.adapters import base
    adapter = _StubAdapter("stub", lambda p: [sys.executable, "-u", "-c", script], streams)
    monkeypatch.setitem(base._ADAPTERS, "stub", adapter)


def _until(predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise TimeoutError("condition not met")


_SLOW_PRINTER = (
    "import time\n"
    "print('step one', flush=True)\n"
    "time.sleep(0.4)\n"
    "print('step two', flush=True)\n"
    "time.sleep(30)\n"
)


class TestTailDispatchTool:
    def test_unknown_id(self, fake_home: Path) -> None:
        r = server.tail_dispatch("nope")
        assert r["ok"] is False

    def test_reads_output_while_the_dispatch_is_still_running(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _SLOW_PRINTER)
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        try:
            r = _until(lambda: (
                t := server.tail_dispatch(d["dispatch_id"])
            )["returned"] >= 2 and t)
            assert r["status"] == "running"
            assert [l["text"] for l in r["lines"]] == ["step one", "step two"]
            assert r["output"]["state"] == "streaming"
            assert r["output"]["output_lines"] == 2
        finally:
            server.cancel_dispatch(d["dispatch_id"])

    def test_second_call_with_the_cursor_returns_only_new_lines(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _SLOW_PRINTER)
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        try:
            first = _until(lambda: (
                t := server.tail_dispatch(d["dispatch_id"])
            )["returned"] >= 1 and t)
            _until(lambda: server.tail_dispatch(d["dispatch_id"])["returned"] >= 2)
            rest = server.tail_dispatch(d["dispatch_id"], since=first["next_since"])
            seen = [l["text"] for l in first["lines"]] + [l["text"] for l in rest["lines"]]
            assert seen == ["step one", "step two"]
        finally:
            server.cancel_dispatch(d["dispatch_id"])

    def test_check_dispatch_reports_output_health_while_running(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _SLOW_PRINTER)
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        try:
            r = _until(lambda: (
                c := server.check_dispatch(d["dispatch_id"])
            )["output"]["output_lines"] >= 1 and c)
            assert r["status"] == "running"
            assert r["output"]["state"] == "streaming"
        finally:
            server.cancel_dispatch(d["dispatch_id"])

    def test_silent_exit_only_agent_is_reported_as_such(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, "import time; time.sleep(30)", streams=False)
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        try:
            r = server.tail_dispatch(d["dispatch_id"])
            assert r["lines"] == []
            assert r["output"]["state"] == "exit_only"
        finally:
            server.cancel_dispatch(d["dispatch_id"])

    def test_progress_reaches_the_shared_db(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another central-mcp process reads the db, not this one's memory."""
        _install(monkeypatch, "print('a'); print('b'); print('c')")
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        _until(lambda: server.check_dispatch(d["dispatch_id"])["status"] != "running")
        progress = dispatches_db.get(d["dispatch_id"])["progress"]
        assert progress["output_lines"] == 3
        assert progress["attempt_count"] == 1
        assert progress["last_output_at"] is not None

    def test_list_dispatches_rows_carry_output_health_when_running(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _SLOW_PRINTER)
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        try:
            listing = server.list_dispatches()
            rows = listing["dispatches"] if isinstance(listing, dict) else listing
            mine = next(r for r in rows if r["dispatch_id"] == d["dispatch_id"])
            assert "output" in mine
        finally:
            server.cancel_dispatch(d["dispatch_id"])

    def test_pulse_in_flight_carries_output_health(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, _SLOW_PRINTER)
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        try:
            _until(lambda: server.tail_dispatch(d["dispatch_id"])["returned"] >= 1)
            snap = pulse.dispatch_snapshot(stub_project)
            assert snap["in_flight"][0]["output"]["state"] in ("streaming", "no_output_yet")
        finally:
            server.cancel_dispatch(d["dispatch_id"])


class TestRenderOutputNote:
    def test_each_state_has_a_distinct_note(self) -> None:
        assert "reports on exit" in pulse._output_note({"state": "exit_only"})
        assert "no output yet" in pulse._output_note({"state": "no_output_yet"})
        assert "quiet" in pulse._output_note(
            {"state": "quiet", "last_output_age_sec": 1200}
        )
        assert "last output" in pulse._output_note(
            {"state": "streaming", "last_output_age_sec": 30}
        )

    def test_missing_health_renders_nothing(self) -> None:
        assert pulse._output_note(None) == ""


class TestProgressFlush:
    def test_lines_before_a_silence_reach_the_db(
        self, stub_project: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An agent that prints and then hangs emits nothing further, so
        the throttled write must be delivered by the timer. Without it the
        db keeps the totals from before the last lines, and a stuck
        dispatch reads as one that never printed."""
        monkeypatch.setattr(server, "_PROGRESS_FLUSH_SEC", 0.3)
        _install(monkeypatch, _SLOW_PRINTER)
        d = server.dispatch(stub_project, "x", permission_mode="bypass")
        try:
            _until(lambda: (
                dispatches_db.get(d["dispatch_id"])["progress"]["output_lines"] == 2
            ))
            entry = dispatches_db.get(d["dispatch_id"])
            assert entry["status"] == "running"
            assert entry["progress"]["last_output_at"] is not None
        finally:
            server.cancel_dispatch(d["dispatch_id"])
