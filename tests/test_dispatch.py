"""Background dispatch coverage (dispatch + check_dispatch + cancel)."""

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

    def exec_argv(self, prompt, *, resume=True):
        return self._argv_fn(prompt)


@pytest.fixture
def stub_project(fake_home: Path, tmp_path: Path) -> str:
    cwd = tmp_path / "stub-cwd"
    cwd.mkdir()
    registry.add_project(name="stubproj", path_=str(cwd), agent="stub")
    return "stubproj"


def _install_stub(monkeypatch: pytest.MonkeyPatch, argv_fn) -> None:
    adapter = _StubAdapter("stub", argv_fn)
    from central_mcp.adapters import base
    monkeypatch.setitem(base._ADAPTERS, "stub", adapter)


def _wait_for_complete(dispatch_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = server.check_dispatch(dispatch_id)
        if r.get("status") != "running":
            return r
        time.sleep(0.1)
    raise TimeoutError(f"dispatch {dispatch_id} still running after {timeout}s")


def test_dispatch_returns_id_immediately(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(monkeypatch, lambda p: [sys.executable, "-c", "import time; time.sleep(1)"])
    r = server.dispatch(stub_project, "x")
    assert r["ok"] is True
    assert "dispatch_id" in r
    assert r["project"] == stub_project
    # Clean up
    server.cancel_dispatch(r["dispatch_id"])


def test_dispatch_check_complete(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(monkeypatch, lambda p: [sys.executable, "-c", f"print({p!r})"])
    r = server.dispatch(stub_project, "hello world")
    result = _wait_for_complete(r["dispatch_id"])
    assert result["status"] == "complete"
    assert result["ok"] is True
    assert "hello world" in result.get("output", "")


def test_dispatch_runs_in_project_cwd(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [sys.executable, "-c", "import os; print(os.getcwd())"],
    )
    r = server.dispatch(stub_project, "ignored")
    result = _wait_for_complete(r["dispatch_id"])
    assert "stub-cwd" in result.get("output", "")


def test_dispatch_nonzero_exit(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(7)"],
    )
    r = server.dispatch(stub_project, "x")
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is False
    assert result["exit_code"] == 7
    assert "boom" in result.get("stderr", "")


def test_dispatch_missing_project(fake_home: Path) -> None:
    r = server.dispatch("no-such-project", "x")
    assert r["ok"] is False
    assert "unknown project" in r["error"]


def test_dispatch_adapter_without_exec(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    registry.add_project(name="cursorproj", path_=str(cwd), agent="cursor")
    r = server.dispatch("cursorproj", "x")
    assert r["ok"] is False
    assert "exec mode" in r["error"]


def test_dispatch_missing_cwd(fake_home: Path, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    registry.add_project(name="ghost", path_=str(missing), agent="claude")
    r = server.dispatch("ghost", "x")
    assert r["ok"] is False
    assert "does not exist" in r["error"]


def test_cancel_dispatch(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    r = server.dispatch(stub_project, "x")
    time.sleep(0.2)
    rc = server.cancel_dispatch(r["dispatch_id"])
    assert rc["ok"] is True
    time.sleep(0.5)
    status = server.check_dispatch(r["dispatch_id"])
    assert status["status"] in ("cancelled", "complete")


def test_list_dispatches(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(monkeypatch, lambda p: [sys.executable, "-c", f"print({p!r})"])
    r = server.dispatch(stub_project, "test-list")
    _wait_for_complete(r["dispatch_id"])
    listing = server.list_dispatches()
    ids = [d["dispatch_id"] for d in listing]
    assert r["dispatch_id"] in ids
