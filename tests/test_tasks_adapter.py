"""Tests for `central_mcp.tasks_adapter` — dispatch ↔ MCP Tasks translation.

Phase 1 of the Ecosystem alignment roadmap track: lock the status
mapping table and the task-object shape before any SDK wiring exists,
so the Phase-2 extension layer can lean on this contract.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from central_mcp import dispatches_db, tasks_adapter


def _entry(status: str = "running", **overrides) -> dict:
    base = {
        "id":      "task0001",
        "project": "myproj",
        "agent":   "claude",
        "status":  status,
        "started": 1_750_000_000.0,
        "result":  None,
    }
    base.update(overrides)
    return base


class TestStatusMapping:
    @pytest.mark.parametrize(
        ("dispatch_status", "expected"),
        [
            ("running",   "working"),
            ("complete",  "completed"),
            ("error",     "failed"),
            ("timeout",   "failed"),
            ("cancelled", "cancelled"),
        ],
    )
    def test_known_statuses(self, dispatch_status: str, expected: str) -> None:
        assert tasks_adapter.task_status(dispatch_status) == expected

    def test_unknown_status_maps_to_working(self) -> None:
        # A future in-flight state misreported as terminal would make
        # pollers abandon a live dispatch — unknown stays non-terminal.
        assert tasks_adapter.task_status("paused") == "working"
        assert tasks_adapter.task_status(None) == "working"

    def test_mapping_covers_every_db_status(self) -> None:
        # The schema comment in dispatches_db is the source of truth for
        # the status column's vocabulary; the mapping must cover it all.
        schema_statuses = {"running", "complete", "error", "cancelled", "timeout"}
        assert set(tasks_adapter.DISPATCH_TO_TASK_STATUS) == schema_statuses

    @pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
    def test_terminal_statuses(self, status: str) -> None:
        assert tasks_adapter.is_terminal(status)

    @pytest.mark.parametrize("status", ["working", "input_required"])
    def test_non_terminal_statuses(self, status: str) -> None:
        assert not tasks_adapter.is_terminal(status)


class TestToTask:
    def test_running_entry(self) -> None:
        task = tasks_adapter.to_task(_entry("running"))
        assert task["taskId"] == "task0001"
        assert task["status"] == "working"
        assert task["pollInterval"] == tasks_adapter.POLL_INTERVAL_MS
        assert task["createdAt"].endswith("+00:00")
        assert "statusMessage" not in task

    def test_meta_carries_project_and_agent(self) -> None:
        task = tasks_adapter.to_task(_entry())
        meta = task["_meta"][tasks_adapter.META_KEY]
        assert meta == {"project": "myproj", "agent": "claude"}

    def test_error_entry_surfaces_error_message(self) -> None:
        task = tasks_adapter.to_task(
            _entry("error", result={"ok": False, "error": "boom"})
        )
        assert task["status"] == "failed"
        assert task["statusMessage"] == "boom"

    def test_error_entry_without_error_text(self) -> None:
        task = tasks_adapter.to_task(_entry("error", result={"ok": False}))
        assert task["statusMessage"] == "dispatch failed"

    def test_timeout_entry(self) -> None:
        task = tasks_adapter.to_task(_entry("timeout"))
        assert task["status"] == "failed"
        assert task["statusMessage"] == "dispatch timed out"

    def test_cancelled_entry(self) -> None:
        task = tasks_adapter.to_task(_entry("cancelled"))
        assert task["status"] == "cancelled"
        assert task["statusMessage"] == "dispatch cancelled"

    def test_missing_started_yields_null_created_at(self) -> None:
        task = tasks_adapter.to_task(_entry(started=None))
        assert task["createdAt"] is None


class TestDbRoundTrip:
    """to_task must accept exactly what dispatches_db hands back."""

    def _start(self) -> None:
        dispatches_db.upsert_started(
            {
                "id":      "rt000001",
                "project": "myproj",
                "agent":   "codex",
                "chain":   ["codex"],
                "prompt":  "do the thing",
                "command": "codex exec 'do the thing'",
                "status":  "running",
                "started": time.time(),
            }
        )

    def test_running_row(self, fake_home: Path) -> None:
        self._start()
        task = tasks_adapter.to_task(dispatches_db.get("rt000001"))
        assert task["status"] == "working"
        assert task["_meta"][tasks_adapter.META_KEY]["agent"] == "codex"

    def test_completed_row(self, fake_home: Path) -> None:
        self._start()
        dispatches_db.upsert_finished(
            "rt000001", "complete", {"ok": True, "exit_code": 0, "output": "done"}
        )
        task = tasks_adapter.to_task(dispatches_db.get("rt000001"))
        assert task["status"] == "completed"
        assert tasks_adapter.is_terminal(task["status"])
        assert "statusMessage" not in task

    def test_failed_row_carries_error(self, fake_home: Path) -> None:
        self._start()
        dispatches_db.upsert_finished(
            "rt000001", "error", {"ok": False, "error": "exit 1"}
        )
        task = tasks_adapter.to_task(dispatches_db.get("rt000001"))
        assert task["status"] == "failed"
        assert task["statusMessage"] == "exit 1"
