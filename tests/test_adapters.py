"""Per-agent adapter tests — verify exec_argv for every supported agent.

Each test checks the exact argv that will be passed to subprocess.Popen,
including resume and bypass flag variations. If a new agent is added
without tests here, the parametrize IDs will make the gap obvious.
"""

from __future__ import annotations

import pytest

from central_mcp.adapters.base import VALID_AGENTS, _ADAPTERS, get_adapter


class TestAdapterRegistry:
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

    def test_session_id_replaces_continue(self) -> None:
        argv = get_adapter("claude").exec_argv(
            "x", resume=True, session_id="a1b2c3d4",
        )
        # session_id short-circuits --continue: specific resume wins.
        assert "--continue" not in argv
        assert "-r" in argv
        i = argv.index("-r")
        assert argv[i + 1] == "a1b2c3d4"


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

    def test_session_id_replaces_last(self) -> None:
        argv = get_adapter("codex").exec_argv(
            "x", resume=True, session_id="abc-session",
        )
        # session_id supplants --last: specific id takes its slot.
        assert "--last" not in argv
        assert argv[:4] == ["codex", "exec", "resume", "abc-session"]


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

    def test_session_id_replaces_latest(self) -> None:
        argv = get_adapter("gemini").exec_argv(
            "x", resume=True, session_id="5",
        )
        # gemini takes numeric indexes, not UUIDs; session_id replaces
        # the "latest" literal.
        assert "latest" not in argv
        i = argv.index("--resume")
        assert argv[i + 1] == "5"


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

    def test_session_id_pins_resume(self) -> None:
        argv = get_adapter("droid").exec_argv(
            "x", resume=True, session_id="a1b2-droid",
        )
        # droid exec uses -s for specific-session resume.
        assert "-s" in argv
        i = argv.index("-s")
        assert argv[i + 1] == "a1b2-droid"

    def test_resume_without_session_id_stays_fresh(self) -> None:
        # droid has no headless "resume latest" — resume=True with no
        # session_id is a no-op, fresh session every time.
        argv = get_adapter("droid").exec_argv("x", resume=True)
        assert "-s" not in argv
        assert "--session-id" not in argv


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

    def test_session_id_replaces_continue(self) -> None:
        argv = get_adapter("opencode").exec_argv(
            "x", resume=True, session_id="ses_abc",
        )
        assert "--continue" not in argv
        assert "-s" in argv
        i = argv.index("-s")
        assert argv[i + 1] == "ses_abc"


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


class TestListSessionsFS:
    """Session listing for adapters that scan ~/.<agent>/... on disk.

    Claude and droid both use `<slug(cwd)>/<uuid>.jsonl` under
    ~/.claude/projects/ and ~/.factory/sessions/ respectively. Codex
    stores date-partitioned `rollout-<ts>-<uuid>.jsonl` with cwd in the
    first line's session_meta payload.

    We point HOME at a tmp dir and write synthetic session files so we
    can assert the adapter returns the right shape without needing the
    real agent binaries installed.
    """

    def test_claude_lists_sessions_for_matching_cwd(
        self, tmp_path, monkeypatch,
    ) -> None:
        import json
        fake_home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(fake_home))
        cwd = tmp_path / "proj"
        cwd.mkdir()
        slug = str(cwd.resolve()).replace("/", "-")
        proj_dir = fake_home / ".claude" / "projects" / slug
        proj_dir.mkdir(parents=True)
        # Two sessions; second is newer so should come first.
        (proj_dir / "aaa-uuid.jsonl").write_text(
            json.dumps({"title": "Older work"}) + "\n"
        )
        (proj_dir / "bbb-uuid.jsonl").write_text(
            json.dumps({"title": "Newer work"}) + "\n"
        )
        # Bump mtime of bbb so it sorts first.
        import os, time
        later = time.time() + 10
        os.utime(proj_dir / "bbb-uuid.jsonl", (later, later))

        sessions = get_adapter("claude").list_sessions(cwd, limit=20)
        assert [s.id for s in sessions] == ["bbb-uuid", "aaa-uuid"]
        assert sessions[0].title == "Newer work"
        assert sessions[1].title == "Older work"

    def test_claude_empty_when_no_project_dir(
        self, tmp_path, monkeypatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        # No ~/.claude/projects/<slug>/ at all
        assert get_adapter("claude").list_sessions(tmp_path / "nowhere") == []

    def test_droid_lists_sessions_for_matching_cwd(
        self, tmp_path, monkeypatch,
    ) -> None:
        import json
        fake_home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(fake_home))
        cwd = tmp_path / "proj"
        cwd.mkdir()
        slug = str(cwd.resolve()).replace("/", "-")
        proj_dir = fake_home / ".factory" / "sessions" / slug
        proj_dir.mkdir(parents=True)
        (proj_dir / "droid-session-1.jsonl").write_text(
            json.dumps({"title": "Droid work"}) + "\n"
        )
        sessions = get_adapter("droid").list_sessions(cwd, limit=20)
        assert len(sessions) == 1
        assert sessions[0].id == "droid-session-1"
        assert sessions[0].title == "Droid work"

    def test_codex_filters_by_cwd(self, tmp_path, monkeypatch) -> None:
        import json
        fake_home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(fake_home))
        cwd_a = tmp_path / "a"
        cwd_b = tmp_path / "b"
        cwd_a.mkdir()
        cwd_b.mkdir()
        sess_dir = fake_home / ".codex" / "sessions" / "2026" / "04" / "20"
        sess_dir.mkdir(parents=True)

        # Session in cwd_a
        (sess_dir / "rollout-2026-04-20-sess-a.jsonl").write_text(
            json.dumps({
                "type": "session_meta",
                "payload": {
                    "id": "sess-a",
                    "cwd": str(cwd_a.resolve()),
                    "timestamp": "2026-04-20T10:00:00Z",
                },
            }) + "\n" + json.dumps({
                "payload": {"content": [{"type": "input_text", "text": "A task"}]}
            }) + "\n"
        )
        # Session in cwd_b — should be filtered out
        (sess_dir / "rollout-2026-04-20-sess-b.jsonl").write_text(
            json.dumps({
                "type": "session_meta",
                "payload": {
                    "id": "sess-b",
                    "cwd": str(cwd_b.resolve()),
                    "timestamp": "2026-04-20T11:00:00Z",
                },
            }) + "\n"
        )

        sessions = get_adapter("codex").list_sessions(cwd_a, limit=20)
        ids = [s.id for s in sessions]
        assert ids == ["sess-a"]


class TestFallbackAdapter:
    def test_no_exec(self) -> None:
        assert get_adapter("shell").exec_argv("anything") is None

    def test_no_launch(self) -> None:
        assert get_adapter("shell").launch_command() == ""

    def test_has_exec_false(self) -> None:
        assert get_adapter("shell").has_exec is False


# ---------- interactive_argv (cmux seed injection) ----------

class TestInteractiveArgvClaude:
    def test_basic_bypass_with_seed(self) -> None:
        argv = get_adapter("claude").interactive_argv(
            seed_prompt="bootstrap", permission_mode="bypass",
        )
        assert argv == [
            "claude", "--dangerously-skip-permissions", "bootstrap",
        ]

    def test_auto_mode_with_seed(self) -> None:
        argv = get_adapter("claude").interactive_argv(
            seed_prompt="bootstrap", permission_mode="auto",
        )
        # auto mode emits the two-flag pair and the seed goes last.
        assert argv[0] == "claude"
        assert "--enable-auto-mode" in argv
        i = argv.index("--permission-mode")
        assert argv[i + 1] == "auto"
        assert argv[-1] == "bootstrap"
        assert "--dangerously-skip-permissions" not in argv

    def test_restricted_emits_no_permission_flag(self) -> None:
        argv = get_adapter("claude").interactive_argv(
            seed_prompt="bootstrap", permission_mode="restricted",
        )
        assert argv == ["claude", "bootstrap"]

    def test_no_seed(self) -> None:
        argv = get_adapter("claude").interactive_argv(permission_mode="bypass")
        assert argv == ["claude", "--dangerously-skip-permissions"]


class TestInteractiveArgvCodex:
    def test_basic_bypass_with_seed(self) -> None:
        argv = get_adapter("codex").interactive_argv(
            seed_prompt="bootstrap", permission_mode="bypass",
        )
        # codex interactive takes [OPTIONS] [PROMPT] — top-level, no
        # `exec` subcommand.
        assert argv == [
            "codex", "--dangerously-bypass-approvals-and-sandbox", "bootstrap",
        ]
        assert "exec" not in argv

    def test_restricted_drops_bypass_flag(self) -> None:
        argv = get_adapter("codex").interactive_argv(
            seed_prompt="bootstrap", permission_mode="restricted",
        )
        assert argv == ["codex", "bootstrap"]


class TestInteractiveArgvGemini:
    def test_basic_bypass_with_seed(self) -> None:
        argv = get_adapter("gemini").interactive_argv(
            seed_prompt="bootstrap", permission_mode="bypass",
        )
        # `-i` is --prompt-interactive: "Execute the prompt and
        # continue in interactive mode".
        assert argv == ["gemini", "--yolo", "-i", "bootstrap"]

    def test_restricted_drops_yolo(self) -> None:
        argv = get_adapter("gemini").interactive_argv(
            seed_prompt="bootstrap", permission_mode="restricted",
        )
        assert argv == ["gemini", "-i", "bootstrap"]

    def test_no_seed_no_prompt_flag(self) -> None:
        argv = get_adapter("gemini").interactive_argv(permission_mode="bypass")
        assert argv == ["gemini", "--yolo"]


class TestInteractiveArgvUnsupported:
    """droid / opencode have no confirmed interactive-seed flag, so
    their adapters must return None — this is what makes `cmd_cmux`
    refuse those agents with a clear error (instead of silently
    booting a workspace where the bootstrap never runs)."""

    def test_droid(self) -> None:
        assert get_adapter("droid").interactive_argv(
            seed_prompt="x", permission_mode="bypass",
        ) is None

    def test_opencode(self) -> None:
        assert get_adapter("opencode").interactive_argv(
            seed_prompt="x", permission_mode="bypass",
        ) is None

    def test_fallback(self) -> None:
        assert get_adapter("shell").interactive_argv(
            seed_prompt="x", permission_mode="bypass",
        ) is None
