"""Subprocess-based dispatch_query coverage.

We don't shell out to a real agent CLI in tests. Instead we point the
project at a tmp dir and monkey-patch `get_adapter` so `exec_argv`
returns a short stub program. That lets us verify the plumbing
(cwd, capture, return shape, error handling, timeout) end-to-end
without depending on claude/codex being installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from central_mcp import registry, server
from central_mcp.adapters.base import Adapter


class _StubAdapter(Adapter):
    def __init__(self, name: str, argv_fn):
        super().__init__(name=name, launch=())
        self._argv_fn = argv_fn

    def exec_argv(self, prompt, *, resume=True):
        return self._argv_fn(prompt)


@pytest.fixture
def stub_project(fake_home: Path, tmp_path: Path) -> str:
    """Register a project whose cwd exists. Returns the project name."""
    cwd = tmp_path / "stub-cwd"
    cwd.mkdir()
    registry.add_project(name="stubproj", path_=str(cwd), agent="stub")
    return "stubproj"


def _install_stub(monkeypatch: pytest.MonkeyPatch, argv_fn) -> None:
    adapter = _StubAdapter("stub", argv_fn)
    from central_mcp.adapters import base
    monkeypatch.setitem(base._ADAPTERS, "stub", adapter)


def test_dispatch_echo_returns_stdout(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(monkeypatch, lambda p: [sys.executable, "-c", f"print({p!r})"])
    result = server.dispatch_query(stub_project, "hello world")  # type: ignore[attr-defined]
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "hello world" in result["output"]
    assert result["project"] == stub_project
    assert "duration_sec" in result


def test_dispatch_runs_in_project_cwd(
    stub_project: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [
            sys.executable, "-c", "import os; print(os.getcwd())",
        ],
    )
    result = server.dispatch_query(stub_project, "ignored")  # type: ignore[attr-defined]
    # Registered cwd is tmp_path/stub-cwd; resolved output should include it
    assert result["ok"] is True
    assert "stub-cwd" in result["output"]


def test_dispatch_nonzero_exit_marks_ok_false(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(7)"],
    )
    result = server.dispatch_query(stub_project, "x")  # type: ignore[attr-defined]
    assert result["ok"] is False
    assert result["exit_code"] == 7
    assert "boom" in result["stderr"]


def test_dispatch_missing_project_error(fake_home: Path) -> None:
    result = server.dispatch_query("no-such-project", "x")  # type: ignore[attr-defined]
    assert result["ok"] is False
    assert "unknown project" in result["error"]


def test_dispatch_adapter_without_exec(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    # cursor adapter has has_exec=False and exec_argv returns None by default
    registry.add_project(name="cursorproj", path_=str(cwd), agent="cursor")
    result = server.dispatch_query("cursorproj", "x")  # type: ignore[attr-defined]
    assert result["ok"] is False
    assert "non-interactive exec mode" in result["error"]


def test_dispatch_missing_cwd(fake_home: Path, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    registry.add_project(name="ghost", path_=str(missing), agent="claude")
    result = server.dispatch_query("ghost", "x")  # type: ignore[attr-defined]
    assert result["ok"] is False
    assert "does not exist" in result["error"]


def test_dispatch_timeout(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [sys.executable, "-c", "import time; time.sleep(10)"],
    )
    result = server.dispatch_query(stub_project, "x", timeout=0.5)  # type: ignore[attr-defined]
    assert result["ok"] is False
    assert "timeout" in result["error"]
