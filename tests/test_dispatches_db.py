"""Tests for `central_mcp.dispatches_db` — shared dispatch state.

The core claim: any central-mcp process that knows the dispatch_id
can look it up via this store, regardless of which process actually
created it. The motivating case is a sub-agent the orchestrator
spawned for polling — it runs in its own process with its own
central-mcp stdio child, so it needs disk-backed state to see
dispatches started by the parent orchestrator's central-mcp.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from central_mcp import dispatches_db


def _sample_entry() -> dict:
    return {
        "id":      "abc12345",
        "project": "myproj",
        "agent":   "claude",
        "chain":   ["claude", "codex"],
        "prompt":  "do the thing",
        "command": "claude -p 'do the thing'",
        "status":  "running",
        "started": time.time(),
    }


class TestStartedThenFinished:
    def test_upsert_started_records_running_entry(
        self, fake_home: Path
    ) -> None:
        dispatches_db.upsert_started(_sample_entry())
        got = dispatches_db.get("abc12345")
        assert got is not None
        assert got["project"] == "myproj"
        assert got["agent"] == "claude"
        assert got["status"] == "running"
        assert got["result"] is None
        assert got["_from_db"] is True

    def test_upsert_finished_sets_terminal_fields(
        self, fake_home: Path
    ) -> None:
        dispatches_db.upsert_started(_sample_entry())
        dispatches_db.upsert_finished(
            "abc12345",
            "complete",
            {
                "ok": True,
                "exit_code": 0,
                "output": "done",
                "stderr": "",
                "duration_sec": 12.3,
                "fallback_used": False,
                "tokens": {"input": 100, "output": 50, "total": 150},
                "agent_used": "claude",
            },
        )
        got = dispatches_db.get("abc12345")
        assert got is not None
        assert got["status"] == "complete"
        assert got["result"]["ok"] is True
        assert got["result"]["exit_code"] == 0
        assert got["result"]["output"] == "done"
        assert got["result"]["duration_sec"] == 12.3
        assert got["result"]["tokens"] == {
            "input": 100, "output": 50, "total": 150,
        }

    def test_upsert_finished_error_preserves_error_field(
        self, fake_home: Path
    ) -> None:
        dispatches_db.upsert_started(_sample_entry())
        dispatches_db.upsert_finished(
            "abc12345",
            "error",
            {"ok": False, "error": "timeout", "exit_code": None},
        )
        got = dispatches_db.get("abc12345")
        assert got["status"] == "error"
        assert got["result"]["ok"] is False
        assert got["result"]["error"] == "timeout"


class TestGet:
    def test_missing_returns_none(self, fake_home: Path) -> None:
        assert dispatches_db.get("does-not-exist") is None


class TestListing:
    def test_list_all_orders_newest_first(
        self, fake_home: Path
    ) -> None:
        for i, tag in enumerate(["old", "mid", "new"]):
            e = _sample_entry()
            e["id"] = f"id-{tag}"
            e["started"] = time.time() + i          # ensure distinct times
            dispatches_db.upsert_started(e)
        rows = dispatches_db.list_all()
        ids = [r["id"] for r in rows]
        assert ids == ["id-new", "id-mid", "id-old"]

    def test_list_active_filters_to_running(
        self, fake_home: Path
    ) -> None:
        for tag in ("a", "b", "c"):
            e = _sample_entry()
            e["id"] = f"id-{tag}"
            dispatches_db.upsert_started(e)
        # mark one complete
        dispatches_db.upsert_finished("id-b", "complete", {"ok": True})
        active = dispatches_db.list_active()
        ids = {r["id"] for r in active}
        assert ids == {"id-a", "id-c"}


class TestIdempotency:
    def test_upsert_started_overwrites(
        self, fake_home: Path
    ) -> None:
        e = _sample_entry()
        dispatches_db.upsert_started(e)
        e["agent"] = "codex"
        dispatches_db.upsert_started(e)
        got = dispatches_db.get("abc12345")
        assert got["agent"] == "codex"

    def test_finished_update_then_second_call_is_noop_safe(
        self, fake_home: Path
    ) -> None:
        dispatches_db.upsert_started(_sample_entry())
        dispatches_db.upsert_finished(
            "abc12345", "complete", {"ok": True, "exit_code": 0}
        )
        # Calling again with different status should update (last write wins).
        dispatches_db.upsert_finished(
            "abc12345", "cancelled", {"ok": False}
        )
        got = dispatches_db.get("abc12345")
        assert got["status"] == "cancelled"


class TestCrossProcessVisibility:
    """The feature that motivates this whole module — the DB read
    must return an entry another (simulated) process wrote, even when
    the caller had no prior knowledge of it.
    """

    def test_subprocess_can_read_parent_written_entry(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        import subprocess
        import os
        # Parent: write a dispatch row
        e = _sample_entry()
        dispatches_db.upsert_started(e)

        # Child: separate Python process, same CENTRAL_MCP_HOME env,
        # reads via the same module.
        env = os.environ.copy()
        env["CENTRAL_MCP_HOME"] = str(fake_home)
        r = subprocess.run(
            ["python", "-c",
             "from central_mcp import dispatches_db; "
             "e = dispatches_db.get('abc12345'); "
             "print(e['project'] if e else 'NONE')"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert r.returncode == 0, r.stderr
        assert "myproj" in r.stdout
