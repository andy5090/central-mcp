"""Tests for dispatch_history (logs-backed) and orchestration_history (timeline-backed)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from central_mcp import registry, server
from central_mcp.adapters.base import Adapter


class _StubAdapter(Adapter):
    def __init__(self, name: str, argv_fn):
        super().__init__(name=name, launch=())
        self._argv_fn = argv_fn

    def exec_argv(self, prompt, *, resume=True, bypass=False):
        return self._argv_fn(prompt)


def _install_stub(monkeypatch: pytest.MonkeyPatch, argv_fn) -> None:
    adapter = _StubAdapter("stub", argv_fn)
    from central_mcp.adapters import base
    monkeypatch.setitem(base._ADAPTERS, "stub", adapter)


def _wait(dispatch_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = server.check_dispatch(dispatch_id)
        if r.get("status") != "running":
            return r
        time.sleep(0.1)
    raise TimeoutError(f"dispatch {dispatch_id} still running after {timeout}s")


class TestDispatchHistory:
    """dispatch_history reads terminal events from the project's jsonl log."""

    def test_single_project_history(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_stub(monkeypatch, lambda p: [sys.executable, "-c", "print('ok')"])
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        registry.add_project(name="alpha", path_=str(cwd), agent="stub")

        r = server.dispatch("alpha", "hello", bypass=True)
        _wait(r["dispatch_id"])

        hist = server.dispatch_history("alpha")
        assert hist["ok"] is True
        assert hist["project"] == "alpha"
        assert hist["count"] >= 1
        rec = hist["records"][0]
        assert rec["dispatch_id"] == r["dispatch_id"]
        assert rec["prompt"] == "hello"
        assert rec["ok"] is True

    def test_unknown_project(self, fake_home: Path) -> None:
        r = server.dispatch_history("ghost")
        assert r["ok"] is False
        assert "unknown project" in r["error"]


class TestOrchestrationHistory:
    """orchestration_history returns a cross-project snapshot."""

    def test_includes_timeline_and_per_project_stats(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_stub(monkeypatch, lambda p: [sys.executable, "-c", "print('ok')"])
        a = tmp_path / "a"
        a.mkdir()
        b = tmp_path / "b"
        b.mkdir()
        registry.add_project(name="alpha", path_=str(a), agent="stub")
        registry.add_project(name="beta", path_=str(b), agent="stub")

        r1 = server.dispatch("alpha", "task1", bypass=True)
        r2 = server.dispatch("beta", "task2", bypass=True)
        _wait(r1["dispatch_id"])
        _wait(r2["dispatch_id"])

        snap = server.orchestration_history()
        assert snap["ok"] is True

        # Timeline covers both dispatched + complete events for both projects.
        projects_in_recent = {rec.get("project") for rec in snap["recent"]}
        assert "alpha" in projects_in_recent
        assert "beta" in projects_in_recent

        # Per-project stats aggregate outcomes.
        assert snap["per_project"]["alpha"]["dispatched"] >= 1
        assert snap["per_project"]["alpha"]["succeeded"] >= 1
        assert snap["per_project"]["beta"]["succeeded"] >= 1

        # Registered projects list included for context.
        names = {p["name"] for p in snap["registered_projects"]}
        assert {"alpha", "beta"} <= names

    def test_in_flight_reports_running_dispatches(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_stub(monkeypatch, lambda p: [sys.executable, "-c", "import time; time.sleep(2)"])
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        registry.add_project(name="slow", path_=str(cwd), agent="stub")

        r = server.dispatch("slow", "long task", bypass=True)
        # Don't wait — it should appear in in_flight right now.
        snap = server.orchestration_history()
        in_flight_ids = {e["dispatch_id"] for e in snap["in_flight"]}
        assert r["dispatch_id"] in in_flight_ids

        server.cancel_dispatch(r["dispatch_id"])
        _wait(r["dispatch_id"])

    def test_window_minutes_filters_old_records(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """window_minutes=0 should drop everything (cutoff in the future).

        This test just verifies the filter is wired, not precise times.
        """
        _install_stub(monkeypatch, lambda p: [sys.executable, "-c", "print('ok')"])
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        registry.add_project(name="alpha", path_=str(cwd), agent="stub")

        r = server.dispatch("alpha", "x", bypass=True)
        _wait(r["dispatch_id"])

        snap = server.orchestration_history(window_minutes=0)
        # 0-minute window → nothing should match (or only records with
        # unparseable timestamps, which we preserve defensively).
        assert snap["ok"] is True
        # Per-project stats should be empty for the real run (filtered out).
        assert snap["per_project"].get("alpha", {}).get("dispatched", 0) == 0
