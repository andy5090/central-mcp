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

    def exec_argv(self, prompt, *, resume=True, permission_mode="restricted"):
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
    r = server.dispatch(stub_project, "x", permission_mode="bypass")
    assert r["ok"] is True
    assert "dispatch_id" in r
    assert r["project"] == stub_project
    # Clean up
    server.cancel_dispatch(r["dispatch_id"])


def test_dispatch_check_complete(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(monkeypatch, lambda p: [sys.executable, "-c", f"print({p!r})"])
    r = server.dispatch(stub_project, "hello world", permission_mode="bypass")
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
    r = server.dispatch(stub_project, "ignored", permission_mode="bypass")
    result = _wait_for_complete(r["dispatch_id"])
    assert "stub-cwd" in result.get("output", "")


def test_dispatch_nonzero_exit(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(7)"],
    )
    r = server.dispatch(stub_project, "x", permission_mode="bypass")
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is False
    assert result["exit_code"] == 7
    assert "boom" in result.get("stderr", "")


def test_dispatch_missing_project(fake_home: Path) -> None:
    r = server.dispatch("no-such-project", "x", permission_mode="bypass")
    assert r["ok"] is False
    assert "unknown project" in r["error"]


def test_dispatch_adapter_without_exec(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    registry.add_project(name="shellproj", path_=str(cwd), agent="shell")
    r = server.dispatch("shellproj", "x", permission_mode="bypass")
    assert r["ok"] is False
    assert "exec mode" in r["error"]


def test_dispatch_missing_cwd(fake_home: Path, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    registry.add_project(name="ghost", path_=str(missing), agent="claude")
    r = server.dispatch("ghost", "x", permission_mode="bypass")
    assert r["ok"] is False
    assert "does not exist" in r["error"]


def test_cancel_dispatch(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(
        monkeypatch,
        lambda p: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    r = server.dispatch(stub_project, "x", permission_mode="bypass")
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
    r = server.dispatch(stub_project, "test-list", permission_mode="bypass")
    _wait_for_complete(r["dispatch_id"])
    listing = server.list_dispatches()
    ids = [d["dispatch_id"] for d in listing]
    assert r["dispatch_id"] in ids


# ---------- agent override + fallback chain ----------


class _TaggedStub(Adapter):
    """Stub that tags its stdout with its own name so attempts are identifiable."""

    def __init__(self, name: str, exit_code: int = 0):
        super().__init__(name=name, launch=())
        self._exit_code = exit_code

    def exec_argv(self, prompt, *, resume=True, permission_mode="restricted"):
        return [
            sys.executable,
            "-c",
            f"import sys; print('ran:{self.name}:'+{prompt!r}); sys.exit({self._exit_code})",
        ]


def _install_adapter(monkeypatch: pytest.MonkeyPatch, adapter: Adapter) -> None:
    from central_mcp.adapters import base
    monkeypatch.setitem(base._ADAPTERS, adapter.name, adapter)


def test_dispatch_agent_override(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dispatch(agent=X) must use X, not the project's registered agent."""
    cwd = tmp_path / "p"
    cwd.mkdir()
    _install_adapter(monkeypatch, _TaggedStub("primary"))
    _install_adapter(monkeypatch, _TaggedStub("override"))
    registry.add_project("p", str(cwd), agent="primary")
    r = server.dispatch("p", "hello", permission_mode="bypass", agent="override")
    assert r["ok"] is True
    assert r["agent"] == "override"
    assert r["chain"] == ["override"]
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is True
    assert "ran:override:hello" in result.get("output", "")
    # Registry must not mutate from a one-shot override.
    proj = registry.find_project("p")
    assert proj.agent == "primary"


def test_dispatch_fallback_used_when_primary_fails(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    _install_adapter(monkeypatch, _TaggedStub("broken", exit_code=42))
    _install_adapter(monkeypatch, _TaggedStub("backup", exit_code=0))
    registry.add_project("p", str(cwd), agent="broken")
    r = server.dispatch("p", "retry-me", permission_mode="bypass", fallback=["backup"])
    assert r["chain"] == ["broken", "backup"]
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is True
    assert result["agent_used"] == "backup"
    assert result["fallback_used"] is True
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["agent"] == "broken"
    assert result["attempts"][0]["ok"] is False
    assert result["attempts"][1]["agent"] == "backup"
    assert result["attempts"][1]["ok"] is True


def test_dispatch_fallback_skipped_when_primary_succeeds(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    _install_adapter(monkeypatch, _TaggedStub("primary", exit_code=0))
    _install_adapter(monkeypatch, _TaggedStub("never", exit_code=0))
    registry.add_project("p", str(cwd), agent="primary")
    r = server.dispatch("p", "ok", permission_mode="bypass", fallback=["never"])
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is True
    assert result["agent_used"] == "primary"
    assert result["fallback_used"] is False
    assert len(result["attempts"]) == 1


def test_dispatch_uses_registry_fallback_when_none_passed(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    _install_adapter(monkeypatch, _TaggedStub("broken", exit_code=1))
    _install_adapter(monkeypatch, _TaggedStub("backup", exit_code=0))
    registry.add_project("p", str(cwd), agent="broken")
    registry.update_project("p", fallback=["backup"])
    r = server.dispatch("p", "hi", permission_mode="bypass")
    assert r["chain"] == ["broken", "backup"]
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is True
    assert result["agent_used"] == "backup"


def test_dispatch_empty_fallback_overrides_registry(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing fallback=[] disables the saved chain for one dispatch."""
    cwd = tmp_path / "p"
    cwd.mkdir()
    _install_adapter(monkeypatch, _TaggedStub("broken", exit_code=1))
    _install_adapter(monkeypatch, _TaggedStub("backup", exit_code=0))
    registry.add_project("p", str(cwd), agent="broken")
    registry.update_project("p", fallback=["backup"])
    r = server.dispatch("p", "hi", permission_mode="bypass", fallback=[])
    assert r["chain"] == ["broken"]
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is False
    assert result["fallback_used"] is False


def test_dispatch_all_agents_fail_reports_last(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    _install_adapter(monkeypatch, _TaggedStub("a", exit_code=1))
    _install_adapter(monkeypatch, _TaggedStub("b", exit_code=2))
    registry.add_project("p", str(cwd), agent="a")
    r = server.dispatch("p", "x", permission_mode="bypass", fallback=["b"])
    result = _wait_for_complete(r["dispatch_id"])
    assert result["ok"] is False
    assert result["agent_used"] == "b"
    assert result["exit_code"] == 2
    assert len(result["attempts"]) == 2


# ---------- update_project MCP tool ----------


def test_update_project_tool_changes_agent(fake_home: Path, tmp_path: Path) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    registry.add_project("p", str(cwd), agent="claude")
    r = server.update_project("p", agent="codex")
    assert r["ok"] is True
    assert r["project"]["agent"] == "codex"
    assert registry.find_project("p").agent == "codex"


def test_update_project_tool_rejects_invalid_agent(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    registry.add_project("p", str(cwd), agent="claude")
    r = server.update_project("p", agent="cursor-agent")
    assert r["ok"] is False
    assert "unknown agent" in r["error"]
    # Registry should be unchanged.
    assert registry.find_project("p").agent == "claude"


def test_update_project_tool_sets_fallback(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    registry.add_project("p", str(cwd), agent="claude")
    r = server.update_project("p", fallback=["codex", "gemini"])
    assert r["ok"] is True
    assert r["project"]["fallback"] == ["codex", "gemini"]


def test_update_project_tool_rejects_invalid_fallback(
    fake_home: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    registry.add_project("p", str(cwd), agent="claude")
    r = server.update_project("p", fallback=["codex", "bogus"])
    assert r["ok"] is False
    assert "unknown agent" in r["error"]
    assert registry.find_project("p").fallback is None


def test_update_project_tool_missing(fake_home: Path) -> None:
    r = server.update_project("ghost", agent="codex")
    assert r["ok"] is False
    assert "not found" in r["error"]


def test_update_project_tool_rejects_shell(fake_home: Path, tmp_path: Path) -> None:
    cwd = tmp_path / "p"
    cwd.mkdir()
    registry.add_project("p", str(cwd), agent="claude")
    r = server.update_project("p", agent="shell")
    assert r["ok"] is False
    assert "shell" in r["error"]
    assert registry.find_project("p").agent == "claude"


def test_dispatch_timeout_does_not_trigger_fallback(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout on primary must surface directly; fallback is for
    genuine failures (token limits, crashes), not stuck agents."""
    cwd = tmp_path / "p"
    cwd.mkdir()

    class _Sleeper(Adapter):
        def exec_argv(self, prompt, *, resume=True, permission_mode="restricted"):
            return [sys.executable, "-c", "import time; time.sleep(30)"]

    _install_adapter(monkeypatch, _Sleeper(name="sleeper", launch=()))
    _install_adapter(monkeypatch, _TaggedStub("backup", exit_code=0))
    registry.add_project("p", str(cwd), agent="sleeper")
    r = server.dispatch("p", "x", permission_mode="bypass", fallback=["backup"], timeout=0.3)
    result = _wait_for_complete(r["dispatch_id"], timeout=5.0)
    assert result["status"] == "timeout"
    assert len(result["attempts"]) == 1, "fallback should NOT run on timeout"
    assert result["attempts"][0]["agent"] == "sleeper"
    assert result["fallback_used"] is False


def test_cancel_stops_fallback_chain(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancel during primary must not let the backup agent run."""
    cwd = tmp_path / "p"
    cwd.mkdir()

    class _Sleeper(Adapter):
        def exec_argv(self, prompt, *, resume=True, permission_mode="restricted"):
            return [sys.executable, "-c", "import time; time.sleep(30)"]

    _install_adapter(monkeypatch, _Sleeper(name="sleeper", launch=()))
    _install_adapter(monkeypatch, _TaggedStub("backup", exit_code=0))
    registry.add_project("p", str(cwd), agent="sleeper")
    r = server.dispatch("p", "x", permission_mode="bypass", fallback=["backup"])
    time.sleep(0.2)
    rc = server.cancel_dispatch(r["dispatch_id"])
    assert rc["ok"] is True
    result = _wait_for_complete(r["dispatch_id"], timeout=5.0)
    assert result["status"] == "cancelled"
    # Backup must NOT have run — the cancel flag is checked before
    # each chain iteration.
    agents_run = [a["agent"] for a in result["attempts"]]
    assert "backup" not in agents_run


# ---------- event log integration ----------

def _read_events(project: str) -> list[dict]:
    import json
    from central_mcp import events as evmod
    path = evmod.log_path(project)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_dispatch_writes_start_and_complete_events(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful dispatch should log start + output + complete events."""
    _install_stub(monkeypatch, lambda p: [sys.executable, "-c", "print('hello')"])
    r = server.dispatch(stub_project, "say hi", permission_mode="bypass")
    _wait_for_complete(r["dispatch_id"])

    records = _read_events(stub_project)
    kinds = [r["event"] for r in records]
    assert "start" in kinds
    assert "complete" in kinds
    # At least one output event from the subprocess stdout.
    assert any(r["event"] == "output" and "hello" in r.get("chunk", "") for r in records)

    # Events from a single dispatch share the dispatch id.
    ids = {r["id"] for r in records}
    assert r["dispatch_id"] in ids


def test_dispatch_event_log_records_error_on_failure(
    stub_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-zero exit should end with a complete event where ok=False."""
    _install_stub(monkeypatch, lambda p: [sys.executable, "-c", "import sys; sys.exit(2)"])
    r = server.dispatch(stub_project, "fail plz", permission_mode="bypass")
    _wait_for_complete(r["dispatch_id"])

    records = _read_events(stub_project)
    terminal = [rec for rec in records if rec["event"] in ("complete", "error")]
    assert terminal, "dispatch produced no terminal event"
    last = terminal[-1]
    assert last["ok"] is False
    assert last.get("exit_code") == 2
