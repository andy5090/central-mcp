"""Workspace-awareness tests for server MCP tools.

Covers:
  - list_projects(workspace=...) — filtered listing
  - dispatch("@ws", ...) — workspace fan-out
  - add_project(..., workspace=...) — register + assign to workspace
  - orchestration_history(workspace=...) — filtered snapshot
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from central_mcp import registry, server
from central_mcp.adapters.base import Adapter


# ---------- shared stub adapter ----------

class _EchoAdapter(Adapter):
    """Prints the prompt and exits 0."""

    def exec_argv(self, prompt, *, resume=True, permission_mode="restricted", session_id=None):
        return [sys.executable, "-c", f"print({prompt!r})"]


def _install_echo(monkeypatch: pytest.MonkeyPatch, name: str = "stub") -> None:
    from central_mcp.adapters import base
    monkeypatch.setitem(base._ADAPTERS, name, _EchoAdapter(name=name, launch=()))


def _wait_for_complete(dispatch_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = server.check_dispatch(dispatch_id)
        if r.get("status") != "running":
            return r
        time.sleep(0.05)
    raise TimeoutError(f"dispatch {dispatch_id} still running after {timeout}s")


# ---------- helpers to set up workspace + projects ----------

def _make_project(tmp_path: Path, name: str, agent: str = "stub") -> str:
    """Register a project and return its name."""
    cwd = tmp_path / name
    cwd.mkdir(exist_ok=True)
    registry.add_project(name=name, path_=str(cwd), agent=agent)
    return name


# ---------- list_projects(workspace=...) ----------


def test_list_projects_no_workspace_returns_all(fake_home: Path, tmp_path: Path) -> None:
    _make_project(tmp_path, "alpha")
    _make_project(tmp_path, "beta")
    result = server.list_projects()
    names = [p["name"] for p in (result if isinstance(result, list) else result["results"])]
    assert "alpha" in names
    assert "beta" in names


def test_list_projects_workspace_filter(fake_home: Path, tmp_path: Path) -> None:
    _make_project(tmp_path, "in-ws")
    _make_project(tmp_path, "out-ws")
    registry.add_workspace("myws")
    registry.add_to_workspace("in-ws", "myws")

    result = server.list_projects(workspace="myws")
    names = [p["name"] for p in (result if isinstance(result, list) else result["results"])]
    assert names == ["in-ws"]
    assert "out-ws" not in names


def test_list_projects_default_workspace_includes_orphans(fake_home: Path, tmp_path: Path) -> None:
    """Projects not assigned to any named workspace appear in 'default'."""
    _make_project(tmp_path, "orphan")
    _make_project(tmp_path, "assigned")
    registry.add_workspace("ws1")
    registry.add_to_workspace("assigned", "ws1")

    result = server.list_projects(workspace="default")
    names = [p["name"] for p in (result if isinstance(result, list) else result["results"])]
    assert "orphan" in names
    assert "assigned" not in names


def test_list_projects_empty_workspace_returns_empty(fake_home: Path, tmp_path: Path) -> None:
    _make_project(tmp_path, "proj")
    registry.add_workspace("emptyws")

    result = server.list_projects(workspace="emptyws")
    projects = result if isinstance(result, list) else result.get("results", [])
    assert projects == []


# ---------- add_project(workspace=...) ----------


def test_add_project_with_workspace_adds_to_registry_and_workspace(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "newproj"
    cwd.mkdir()
    registry.add_workspace("target-ws")

    r = server.add_project("newproj", str(cwd), agent="claude", workspace="target-ws")
    assert r["ok"] is True
    assert r["project"]["name"] == "newproj"
    assert r.get("workspace") == "target-ws"

    # Project must actually appear in the workspace.
    members = registry.projects_in_workspace("target-ws")
    assert any(p.name == "newproj" for p in members)


def test_add_project_with_nonexistent_workspace_warns(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    # Don't create the workspace — should warn, not hard-fail.
    r = server.add_project("proj", str(cwd), agent="claude", workspace="ghost-ws")
    assert r["ok"] is True  # project was still registered
    assert "workspace_warning" in r
    assert registry.find_project("proj") is not None


def test_add_project_without_workspace_param_unchanged(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "plain"
    cwd.mkdir()
    r = server.add_project("plain", str(cwd), agent="claude")
    assert r["ok"] is True
    assert "workspace" not in r
    assert "workspace_warning" not in r


# ---------- dispatch("@workspace", ...) ----------


def test_dispatch_workspace_fanout(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dispatch('@ws', prompt) must create one dispatch per workspace member."""
    _install_echo(monkeypatch, "stub")
    _make_project(tmp_path, "ws-proj-a")
    _make_project(tmp_path, "ws-proj-b")
    registry.add_workspace("fanout-ws")
    registry.add_to_workspace("ws-proj-a", "fanout-ws")
    registry.add_to_workspace("ws-proj-b", "fanout-ws")

    r = server.dispatch("@fanout-ws", "hello workspace", permission_mode="bypass")
    assert r["ok"] is True
    assert r["workspace"] == "fanout-ws"
    assert len(r["dispatches"]) == 2

    projects_dispatched = {d["project"] for d in r["dispatches"]}
    assert projects_dispatched == {"ws-proj-a", "ws-proj-b"}

    # Each member dispatch must have its own dispatch_id and ok=True.
    for d in r["dispatches"]:
        assert d.get("ok") is True
        assert "dispatch_id" in d

    # Clean up background threads.
    for d in r["dispatches"]:
        server.cancel_dispatch(d["dispatch_id"])


def test_dispatch_workspace_fanout_completes(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each fan-out dispatch must actually complete with ok=True."""
    _install_echo(monkeypatch, "stub")
    _make_project(tmp_path, "c1")
    _make_project(tmp_path, "c2")
    registry.add_workspace("complete-ws")
    registry.add_to_workspace("c1", "complete-ws")
    registry.add_to_workspace("c2", "complete-ws")

    r = server.dispatch("@complete-ws", "ping", permission_mode="bypass")
    assert r["ok"] is True

    for d in r["dispatches"]:
        result = _wait_for_complete(d["dispatch_id"])
        assert result["ok"] is True


def test_dispatch_workspace_empty_returns_error(fake_home: Path, tmp_path: Path) -> None:
    registry.add_workspace("no-members")
    r = server.dispatch("@no-members", "hello", permission_mode="bypass")
    assert r["ok"] is False
    assert "no-members" in r["error"]


def test_dispatch_workspace_nonexistent_returns_error(fake_home: Path) -> None:
    r = server.dispatch("@ghost-workspace", "hello", permission_mode="bypass")
    assert r["ok"] is False
    assert "ghost-workspace" in r["error"]


def test_dispatch_single_project_still_works(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-@ dispatch must continue to work as before after refactor."""
    _install_echo(monkeypatch, "stub")
    _make_project(tmp_path, "solo")
    r = server.dispatch("solo", "test", permission_mode="bypass")
    assert r["ok"] is True
    assert "dispatch_id" in r
    assert r["project"] == "solo"
    server.cancel_dispatch(r["dispatch_id"])


# ---------- orchestration_history(workspace=...) ----------


def test_orchestration_history_workspace_filters_registered_projects(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """registered_projects in the snapshot must be limited to the workspace."""
    _install_echo(monkeypatch, "stub")
    _make_project(tmp_path, "ws-only")
    _make_project(tmp_path, "outside")
    registry.add_workspace("hist-ws")
    registry.add_to_workspace("ws-only", "hist-ws")

    snap = server.orchestration_history(workspace="hist-ws")
    assert snap["ok"] is True
    reg_names = [p["name"] for p in snap["registered_projects"]]
    assert "ws-only" in reg_names
    assert "outside" not in reg_names


def test_orchestration_history_workspace_filters_in_flight(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """in_flight list must exclude dispatches for projects outside the workspace."""
    from central_mcp.adapters import base

    class _Sleeper(Adapter):
        def exec_argv(self, prompt, *, resume=True, permission_mode="restricted", session_id=None):
            return [sys.executable, "-c", "import time; time.sleep(30)"]

    base._ADAPTERS["sleeper"] = _Sleeper(name="sleeper", launch=())
    try:
        cwd_in = tmp_path / "in"
        cwd_in.mkdir()
        cwd_out = tmp_path / "out"
        cwd_out.mkdir()
        registry.add_project("in-proj", str(cwd_in), agent="sleeper")
        registry.add_project("out-proj", str(cwd_out), agent="sleeper")
        registry.add_workspace("inflight-ws")
        registry.add_to_workspace("in-proj", "inflight-ws")

        r_in = server.dispatch("in-proj", "x", permission_mode="bypass")
        r_out = server.dispatch("out-proj", "x", permission_mode="bypass")
        time.sleep(0.1)

        snap = server.orchestration_history(workspace="inflight-ws")
        in_flight_projects = {d["project"] for d in snap["in_flight"]}
        assert "in-proj" in in_flight_projects
        assert "out-proj" not in in_flight_projects
    finally:
        base._ADAPTERS.pop("sleeper", None)
        server.cancel_dispatch(r_in["dispatch_id"])
        server.cancel_dispatch(r_out["dispatch_id"])


def test_orchestration_history_no_workspace_returns_all(
    fake_home: Path, tmp_path: Path
) -> None:
    _make_project(tmp_path, "p1")
    _make_project(tmp_path, "p2")
    snap = server.orchestration_history()
    reg_names = [p["name"] for p in snap["registered_projects"]]
    assert "p1" in reg_names
    assert "p2" in reg_names
