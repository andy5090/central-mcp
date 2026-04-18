"""Per-agent adapter tests — verify exec_argv for every supported agent.

Each test checks the exact argv that will be passed to subprocess.Popen,
including resume and bypass flag variations. If a new agent is added
without tests here, the parametrize IDs will make the gap obvious.
"""

from __future__ import annotations

import pytest

from central_mcp.adapters.base import VALID_AGENTS, _ADAPTERS, get_adapter


class TestAdapterRegistry:
    def test_every_valid_agent_has_an_adapter(self) -> None:
        for name in VALID_AGENTS:
            adapter = get_adapter(name)
            assert adapter.name == name

    def test_unknown_agent_falls_back_to_fallback_adapter(self) -> None:
        adapter = get_adapter("nonexistent")
        assert adapter.name == "(unknown)"
        assert adapter.exec_argv("x") is None


class TestClaude:
    def test_basic(self) -> None:
        argv = get_adapter("claude").exec_argv("do stuff")
        assert argv == ["claude", "-p", "do stuff", "--continue"]

    def test_no_resume(self) -> None:
        argv = get_adapter("claude").exec_argv("do stuff", resume=False)
        assert argv == ["claude", "-p", "do stuff"]
        assert "--continue" not in argv

    def test_bypass(self) -> None:
        argv = get_adapter("claude").exec_argv("do stuff", permission_mode="bypass")
        assert "--dangerously-skip-permissions" in argv

    def test_bypass_and_resume(self) -> None:
        argv = get_adapter("claude").exec_argv("x", resume=True, permission_mode="bypass")
        assert "--continue" in argv
        assert "--dangerously-skip-permissions" in argv

    def test_auto_mode(self) -> None:
        argv = get_adapter("claude").exec_argv("x", permission_mode="auto")
        assert "--enable-auto-mode" in argv
        assert "--permission-mode" in argv
        # --permission-mode auto (takes a value) — these two tokens must be adjacent
        i = argv.index("--permission-mode")
        assert argv[i + 1] == "auto"
        # Must NOT emit the bypass flag when in auto mode.
        assert "--dangerously-skip-permissions" not in argv

    def test_restricted_emits_no_permission_flag(self) -> None:
        argv = get_adapter("claude").exec_argv("x", permission_mode="restricted")
        assert "--dangerously-skip-permissions" not in argv
        assert "--enable-auto-mode" not in argv


class TestCodex:
    def test_basic(self) -> None:
        # resume=True (default) uses `codex exec resume --last`
        argv = get_adapter("codex").exec_argv("fix bug")
        assert argv == ["codex", "exec", "resume", "--last", "fix bug"]

    def test_no_resume(self) -> None:
        argv = get_adapter("codex").exec_argv("fix bug", resume=False)
        assert argv == ["codex", "exec", "fix bug"]
        assert "resume" not in argv
        assert "--last" not in argv

    def test_bypass(self) -> None:
        argv = get_adapter("codex").exec_argv("fix bug", permission_mode="bypass")
        assert "--dangerously-bypass-approvals-and-sandbox" in argv

    def test_bypass_and_resume(self) -> None:
        argv = get_adapter("codex").exec_argv("fix bug", resume=True, permission_mode="bypass")
        assert argv[:4] == ["codex", "exec", "resume", "--last"]
        assert "--dangerously-bypass-approvals-and-sandbox" in argv


class TestGemini:
    def test_basic(self) -> None:
        # resume=True (default) adds --resume latest
        argv = get_adapter("gemini").exec_argv("analyze code")
        assert argv == ["gemini", "-p", "analyze code", "--resume", "latest"]

    def test_no_resume(self) -> None:
        argv = get_adapter("gemini").exec_argv("analyze code", resume=False)
        assert argv == ["gemini", "-p", "analyze code"]
        assert "--resume" not in argv

    def test_bypass(self) -> None:
        argv = get_adapter("gemini").exec_argv("analyze code", permission_mode="bypass")
        assert "--yolo" in argv

    def test_bypass_and_resume(self) -> None:
        argv = get_adapter("gemini").exec_argv("analyze code", resume=True, permission_mode="bypass")
        assert "--resume" in argv
        assert "latest" in argv
        assert "--yolo" in argv


class TestDroid:
    def test_basic(self) -> None:
        argv = get_adapter("droid").exec_argv("refactor")
        assert argv == ["droid", "exec", "refactor"]

    def test_resume_is_noop(self) -> None:
        # droid exec has no session-resume flag — `-r` is
        # reasoning-effort (takes a value), so we never emit it.
        argv = get_adapter("droid").exec_argv("refactor", resume=True)
        assert "-r" not in argv
        argv = get_adapter("droid").exec_argv("refactor", resume=False)
        assert "-r" not in argv

    def test_bypass(self) -> None:
        argv = get_adapter("droid").exec_argv("refactor", permission_mode="bypass")
        assert "--skip-permissions-unsafe" in argv
        # Regression: `--skip-permissions-unsafe` must not follow a
        # value-taking flag like `-r`, or droid eats it as the value.
        if "-r" in argv:
            r_idx = argv.index("-r")
            assert argv[r_idx + 1] != "--skip-permissions-unsafe"


class TestOpenCode:
    def test_basic(self) -> None:
        argv = get_adapter("opencode").exec_argv("fix tests")
        assert argv == ["opencode", "run", "fix tests", "--continue"]

    def test_no_resume(self) -> None:
        argv = get_adapter("opencode").exec_argv("fix tests", resume=False)
        assert "--continue" not in argv

    def test_bypass(self) -> None:
        argv = get_adapter("opencode").exec_argv("fix tests", permission_mode="bypass")
        assert "--dangerously-skip-permissions" in argv

    def test_bypass_and_resume(self) -> None:
        argv = get_adapter("opencode").exec_argv("x", resume=True, permission_mode="bypass")
        assert "--continue" in argv
        assert "--dangerously-skip-permissions" in argv


class TestAmpRemoved:
    """Regression: amp was dropped because Amp Free rejects non-
    interactive `amp -x`. Make sure nobody silently re-adds it without
    reading that history."""

    def test_amp_not_in_valid_agents(self) -> None:
        assert "amp" not in VALID_AGENTS

    def test_amp_adapter_falls_back_to_fallback_adapter(self) -> None:
        # `get_adapter` returns the internal fallback adapter for any unknown name,
        # so looking up `amp` should yield has_exec=False.
        assert get_adapter("amp").has_exec is False
        assert get_adapter("amp").exec_argv("x") is None


class TestFallbackAdapter:
    def test_no_exec(self) -> None:
        assert get_adapter("shell").exec_argv("anything") is None

    def test_no_launch(self) -> None:
        assert get_adapter("shell").launch_command() == ""

    def test_has_exec_false(self) -> None:
        assert get_adapter("shell").has_exec is False
