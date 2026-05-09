"""PTY session registry — register / sweep / dispatch-guard contract."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from central_mcp import pty_sessions


def test_register_creates_entry(fake_home: Path) -> None:
    pty_sessions.register("my-app", os.getpid(), "claude")

    assert pty_sessions.is_active("my-app")
    entry = pty_sessions.get("my-app")
    assert entry is not None
    assert entry["project"] == "my-app"
    assert entry["pid"] == os.getpid()
    assert entry["agent"] == "claude"
    assert "started_at" in entry


def test_unregister_removes_entry(fake_home: Path) -> None:
    pty_sessions.register("my-app", os.getpid(), "claude")
    assert pty_sessions.is_active("my-app")

    pty_sessions.unregister("my-app")
    assert not pty_sessions.is_active("my-app")


def test_unregister_missing_is_noop(fake_home: Path) -> None:
    """Unregistering a project that was never registered must not raise."""
    pty_sessions.unregister("never-registered")
    assert not pty_sessions.is_active("never-registered")


def test_stale_pid_swept_on_read(fake_home: Path) -> None:
    """A registration whose PID is gone must be removed on the next is_active().

    Simulates a TUI crash that left the json file behind. We pick a PID
    that's vanishingly unlikely to be live: 2**31 - 1 is well past
    PID_MAX on every OS we support.
    """
    pty_sessions.register("ghost", 2**31 - 1, "claude")
    # First read sees the file but detects stale PID and sweeps it.
    assert not pty_sessions.is_active("ghost")
    # File should be gone now — second read shows no entry without sweeping.
    entry_path = pty_sessions._entry_path("ghost")
    assert not entry_path.exists()


def test_corrupt_entry_swept(fake_home: Path) -> None:
    """A non-JSON file in the registry directory is removed on read."""
    d = pty_sessions._registry_dir()
    d.mkdir(parents=True, exist_ok=True)
    bad = d / "corrupt.json"
    bad.write_text("{not valid json", encoding="utf-8")

    assert not pty_sessions.is_active("corrupt")
    assert not bad.exists()


def test_list_active_filters_stale(fake_home: Path) -> None:
    pty_sessions.register("alive", os.getpid(), "claude")
    pty_sessions.register("dead", 2**31 - 1, "codex")

    rows = pty_sessions.list_active()
    names = {r["project"] for r in rows}
    assert names == {"alive"}


def test_list_active_empty_when_dir_missing(fake_home: Path) -> None:
    """No registrations yet → empty list, no error from missing directory."""
    assert pty_sessions.list_active() == []


def test_dispatch_blocked_when_pty_active(
    fake_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dispatch()` must refuse when the project has a live PTY pane.

    The error explicitly carries `mode: "pty"` so orchestrators can
    branch their fallback path without having to string-match the
    error message.
    """
    from central_mcp import registry, server

    cwd = tmp_path / "guarded-cwd"
    cwd.mkdir()
    registry.add_project(name="guarded", path_=str(cwd), agent="claude")

    pty_sessions.register("guarded", os.getpid(), "claude")

    r = server.dispatch("guarded", "hello", permission_mode="bypass")

    assert r["ok"] is False
    assert r["mode"] == "pty"
    assert "PTY mode" in r["error"]


def test_dispatch_proceeds_after_pty_unregister(
    fake_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping the PTY registration restores normal dispatch behavior.

    Using a real subprocess via the stub adapter would slow the suite
    here; the contract we want to lock is just "guard no longer fires"
    — `_launch_dispatch` getting past the PTY check is sufficient
    evidence. We assert by checking the error shape changes (no longer
    `mode: "pty"`) and the dispatch_id field appears.
    """
    import sys
    from central_mcp import registry, server
    from central_mcp.adapters import base
    from central_mcp.adapters.base import Adapter

    cwd = tmp_path / "ungated-cwd"
    cwd.mkdir()
    registry.add_project(name="ungated", path_=str(cwd), agent="stub")

    class _StubAdapter(Adapter):
        def __init__(self) -> None:
            super().__init__(name="stub", launch=())

        def exec_argv(self, prompt, *, resume=True, permission_mode="restricted", session_id=None):
            return [sys.executable, "-c", "print('ok')"]

    monkeypatch.setitem(base._ADAPTERS, "stub", _StubAdapter())

    pty_sessions.register("ungated", os.getpid(), "stub")
    blocked = server.dispatch("ungated", "x", permission_mode="bypass")
    assert blocked["ok"] is False
    assert blocked["mode"] == "pty"

    pty_sessions.unregister("ungated")
    allowed = server.dispatch("ungated", "x", permission_mode="bypass")
    assert allowed["ok"] is True
    assert "dispatch_id" in allowed
    server.cancel_dispatch(allowed["dispatch_id"])
