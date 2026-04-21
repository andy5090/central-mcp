"""Tests for the cmux observation backend (agent-driven layout).

The shipped cmux CLI (0.63.2) doesn't have a declarative `--layout`
flag, so central-mcp delegates pane construction to the orchestrator:
`cmd_cmux` opens a single-pane workspace seeded with a prompt that
instructs the agent to call `cmux new-split` / `cmux send-text` for
each registered project.

These tests cover the thin surface central-mcp owns: the
subprocess-mocked workspace helpers (`has_workspace`,
`ensure_workspace`, `kill_workspace`) and the seed-prompt builder.
Agent-side behavior (does claude really run the bootstrap?) is out
of scope — those are live integration tests against the real CLIs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from central_mcp import cmux
from central_mcp.registry import Project


# ---------- subprocess fake ----------

class _FakeRun:
    """Records calls and returns canned CmuxResult-like objects."""

    def __init__(self, responses: list[cmux.CmuxResult]) -> None:
        self.calls: list[list[str]] = []
        self._responses = list(responses)

    def __call__(self, args: list[str]) -> cmux.CmuxResult:
        self.calls.append(list(args))
        if not self._responses:
            return cmux.CmuxResult(ok=True, stdout="", stderr="")
        return self._responses.pop(0)


class TestHasWorkspace:
    def test_true_when_workspace_titled_central_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "w1", "title": cmux.SESSION, "ref": "workspace:0"}]}
        )
        fake = _FakeRun([cmux.CmuxResult(ok=True, stdout=payload, stderr="")])
        monkeypatch.setattr(cmux, "_run", fake)
        assert cmux.has_workspace(cmux.SESSION) is True
        # --json is a GLOBAL flag — must come before the subcommand.
        assert fake.calls == [["--json", "list-workspaces"]]

    def test_false_when_no_matching_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "w1", "title": "something-else"}]}
        )
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=True, stdout=payload, stderr="")]),
        )
        assert cmux.has_workspace(cmux.SESSION) is False

    def test_false_when_list_command_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=False, stdout="", stderr="boom")]),
        )
        assert cmux.has_workspace(cmux.SESSION) is False

    def test_false_when_output_is_not_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=True, stdout="not json", stderr="")]),
        )
        assert cmux.has_workspace(cmux.SESSION) is False


class TestKillWorkspace:
    def test_noop_when_nothing_to_kill(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = json.dumps({"workspaces": []})
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=True, stdout=empty, stderr="")]),
        )
        r = cmux.kill_workspace(cmux.SESSION)
        assert r.ok is True
        assert "no workspace" in r.stderr

    def test_uses_ref_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [
                {"id": "uuid-1", "title": cmux.SESSION, "ref": "workspace:0"},
            ]}
        )
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=payload, stderr=""),
            cmux.CmuxResult(ok=True, stdout="", stderr=""),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        r = cmux.kill_workspace(cmux.SESSION)
        assert r.ok is True
        # Second call should be close-workspace with the ref form.
        assert fake.calls[1] == ["close-workspace", "--workspace", "workspace:0"]

    def test_falls_back_to_id_when_no_ref(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "uuid-1", "title": cmux.SESSION}]}
        )
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=payload, stderr=""),
            cmux.CmuxResult(ok=True, stdout="", stderr=""),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        cmux.kill_workspace(cmux.SESSION)
        assert fake.calls[1] == ["close-workspace", "--workspace", "uuid-1"]


class TestEnsureWorkspace:
    """`ensure_workspace` accepts an optional orchestrator cwd + shell
    command. No declarative layout builder is involved — cmux 0.63.2
    only accepts `--name / --cwd / --command` on `new-workspace`."""

    def test_no_op_when_workspace_already_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "w1", "title": cmux.SESSION}]}
        )
        fake = _FakeRun([cmux.CmuxResult(ok=True, stdout=payload, stderr="")])
        monkeypatch.setattr(cmux, "_run", fake)
        created, messages = cmux.ensure_workspace(
            orchestrator_cwd="/tmp/ignored",
            shell_command="claude 'ignored'",
        )
        assert created is False
        assert any("already exists" in m for m in messages)
        # Only the probe call — no new-workspace was issued.
        assert fake.calls == [["--json", "list-workspaces"]]

    def test_creates_workspace_with_cwd_and_command(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = json.dumps({"workspaces": []})
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=empty, stderr=""),
            cmux.CmuxResult(ok=True, stdout="OK wsid", stderr=""),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        created, messages = cmux.ensure_workspace(
            orchestrator_cwd="/Users/me/.central-mcp",
            shell_command="claude --dangerously-skip-permissions 'seed'",
        )
        assert created is True
        assert any("opened via cmux" in m for m in messages)
        assert fake.calls[1] == [
            "new-workspace",
            "--name", cmux.SESSION,
            "--cwd", "/Users/me/.central-mcp",
            "--command", "claude --dangerously-skip-permissions 'seed'",
        ]

    def test_creates_bare_workspace_when_no_orchestrator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--no-orchestrator` path: ensure_workspace is called with no
        args, should emit just `new-workspace --name central`."""
        empty = json.dumps({"workspaces": []})
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=empty, stderr=""),
            cmux.CmuxResult(ok=True, stdout="", stderr=""),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        created, _ = cmux.ensure_workspace()
        assert created is True
        assert fake.calls[1] == ["new-workspace", "--name", cmux.SESSION]

    def test_surfaces_stderr_on_new_workspace_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = json.dumps({"workspaces": []})
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=empty, stderr=""),
            cmux.CmuxResult(ok=False, stdout="", stderr="socket refused"),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        created, messages = cmux.ensure_workspace()
        assert created is False
        assert any("socket refused" in m for m in messages)


class TestSeedPrompt:
    """`build_cmux_seed_prompt` produces a self-contained bootstrap
    prompt: the agent reads it, iterates the embedded project list,
    and calls the cmux CLI from its Bash tool. No MCP calls needed,
    so the prompt survives even a cold cmux workspace where MCP
    tools haven't warmed up."""

    def test_empty_registry_returns_empty_string(self) -> None:
        assert cmux.build_cmux_seed_prompt([]) == ""

    def test_includes_every_project_name(self) -> None:
        projects = [
            Project(name="alpha", path="/tmp/alpha"),
            Project(name="beta", path="/tmp/beta"),
            Project(name="gamma", path="/tmp/gamma"),
        ]
        prompt = cmux.build_cmux_seed_prompt(projects)
        for p in projects:
            assert p.name in prompt
        # Count appearance is exact — project names should each show
        # up in the bullet list and once as the watch-command target.
        assert prompt.count("  - alpha\n") == 1
        assert prompt.count("  - beta\n") == 1

    def test_mentions_cmux_env_var_and_bootstrap_commands(self) -> None:
        prompt = cmux.build_cmux_seed_prompt(
            [Project(name="solo", path="/tmp/solo")]
        )
        # The env var cmux injects into its panes — the agent keys
        # all its CLI calls off of this.
        assert "CMUX_WORKSPACE_ID" in prompt
        # Exact cmux verbs the agent is expected to call.
        for verb in ("cmux new-split", "cmux --json list-pane-surfaces", "cmux send-text"):
            assert verb in prompt
        # Must tell the agent to run central-mcp watch inside each pane.
        assert "central-mcp watch" in prompt

    def test_self_contained_completion_signal(self) -> None:
        projects = [
            Project(name="a", path="/x"),
            Project(name="b", path="/y"),
        ]
        prompt = cmux.build_cmux_seed_prompt(projects)
        assert f"observation layer ready: {len(projects)} project(s)" in prompt


# ---------- platform gating ----------

class TestDetectMultiplexersPlatformGating:
    """`cmux` is macOS-only — confirm `_detect_multiplexers` only offers
    it on darwin even when the binary happens to be on PATH."""

    def test_cmux_excluded_on_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.cli import _commands

        monkeypatch.setattr(_commands.platform, "system", lambda: "Linux")
        monkeypatch.setattr(_commands.shutil, "which", lambda _b: "/fake/bin")
        names = [name for name, _bin in _commands._detect_multiplexers()]
        assert "cmux" not in names
        assert "tmux" in names
        assert "zellij" in names

    def test_cmux_included_on_darwin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.cli import _commands

        monkeypatch.setattr(_commands.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(_commands.shutil, "which", lambda _b: "/fake/bin")
        names = [name for name, _bin in _commands._detect_multiplexers()]
        assert "cmux" in names
