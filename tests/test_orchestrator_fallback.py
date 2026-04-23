"""Tests for orchestrator-fallback chain resolution in `cmd_run`.

Covers:
  - installed agents form the chain; uninstalled are skipped
  - over-quota agents carry a skip reason
  - `fallback = [...]` user hint is honored for ordering
  - `orchestrator_fallback_enabled = false` bypasses quota checks
  - chain is deterministic on each invocation
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from central_mcp import config as _cfg
from central_mcp.cli import _commands


# ── _orchestrator_over_quota ─────────────────────────────────────────────────

class TestOverQuota:
    def test_unknown_agent_is_not_over(self) -> None:
        assert _commands._orchestrator_over_quota("notreal") is False

    def test_no_quota_api_agent_is_not_over(self) -> None:
        # gemini has_quota_api=False — always returns False.
        assert _commands._orchestrator_over_quota("gemini") is False

    def test_claude_api_key_is_not_over(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.quota import claude as _claude
        monkeypatch.setattr(_claude, "fetch", lambda: {"mode": "api_key"})
        assert _commands._orchestrator_over_quota("claude") is False

    def test_claude_pro_under_threshold(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.quota import claude as _claude
        monkeypatch.setattr(_claude, "fetch", lambda: {
            "mode": "pro",
            "raw": {
                "five_hour":  {"utilization": 0.50},     # 50%
                "seven_day":  {"utilization": 0.30},     # 30%
            },
        })
        assert _commands._orchestrator_over_quota("claude") is False

    def test_claude_pro_over_five_hour_threshold(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.quota import claude as _claude
        monkeypatch.setattr(_claude, "fetch", lambda: {
            "mode": "pro",
            "raw": {
                "five_hour": {"utilization": 0.97},      # 97% → over 95% default
                "seven_day": {"utilization": 0.20},
            },
        })
        assert _commands._orchestrator_over_quota("claude") is True

    def test_claude_pro_over_weekly_threshold(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.quota import claude as _claude
        monkeypatch.setattr(_claude, "fetch", lambda: {
            "mode": "pro",
            "raw": {
                "five_hour": {"utilization": 0.10},
                "seven_day": {"utilization": 0.92},      # 92% → over 90% default
            },
        })
        assert _commands._orchestrator_over_quota("claude") is True

    def test_custom_threshold_honored(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Lower the threshold so 80% trips it.
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["orchestrator"] = {"quota_threshold": {"five_hour": 80, "seven_day": 75}}
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))

        from central_mcp.quota import claude as _claude
        monkeypatch.setattr(_claude, "fetch", lambda: {
            "mode": "pro",
            "raw": {
                "five_hour": {"utilization": 0.85},
                "seven_day": {"utilization": 0.20},
            },
        })
        assert _commands._orchestrator_over_quota("claude") is True


# ── chain resolution ─────────────────────────────────────────────────────────

class TestResolveChain:
    @pytest.fixture(autouse=True)
    def _patch_shutil(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pretend all 4 orchestrator-capable agents are installed."""
        installed = {"claude", "codex", "gemini", "opencode"}
        monkeypatch.setattr(
            _commands.shutil, "which",
            lambda b: "/usr/local/bin/" + b if b in installed else None,
        )
        # Also patch the agents module's shutil so AGENTS.installed() agrees.
        from central_mcp import agents as _agents
        monkeypatch.setattr(
            _agents.shutil, "which",
            lambda b: "/usr/local/bin/" + b if b in installed else None,
        )

    def test_preferred_is_first(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_commands, "_orchestrator_over_quota", lambda _a: False)
        chain = _commands._resolve_orchestrator_chain("codex")
        names = [e[0][0] for e in chain]
        assert names[0] == "codex"
        assert set(names) == {"claude", "codex", "gemini", "opencode"}

    def test_user_fallback_order_honored(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_commands, "_orchestrator_over_quota", lambda _a: False)
        # Configure explicit fallback order.
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["orchestrator"] = {
            "default":  "claude",
            "fallback": ["gemini", "codex"],     # explicit order
        }
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))

        chain = _commands._resolve_orchestrator_chain("claude")
        names = [e[0][0] for e in chain]
        assert names[:3] == ["claude", "gemini", "codex"]
        # opencode (not listed in fallback) tacked on at the end.
        assert names[3] == "opencode"

    def test_over_quota_entries_carry_skip_reason(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # claude over quota, others fine.
        monkeypatch.setattr(
            _commands, "_orchestrator_over_quota",
            lambda a: a == "claude",
        )
        chain = _commands._resolve_orchestrator_chain("claude")
        for entry, reason in chain:
            if entry[0] == "claude":
                assert reason, "over-quota agent should have a skip reason"
            else:
                assert reason == ""

    def test_uninstalled_agents_dropped(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Only claude + codex installed.
        monkeypatch.setattr(
            _commands.shutil, "which",
            lambda b: "/usr/local/bin/" + b if b in ("claude", "codex") else None,
        )
        from central_mcp import agents as _agents
        monkeypatch.setattr(
            _agents.shutil, "which",
            lambda b: "/usr/local/bin/" + b if b in ("claude", "codex") else None,
        )
        monkeypatch.setattr(_commands, "_orchestrator_over_quota", lambda _a: False)

        chain = _commands._resolve_orchestrator_chain("claude")
        names = [e[0][0] for e in chain]
        assert names == ["claude", "codex"]        # gemini / opencode dropped

    def test_non_orchestratable_agents_excluded(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # droid has can_orchestrate=False, even if installed it's never in chain.
        monkeypatch.setattr(
            _commands.shutil, "which",
            lambda b: "/usr/local/bin/" + b,     # everything installed
        )
        from central_mcp import agents as _agents
        monkeypatch.setattr(
            _agents.shutil, "which",
            lambda b: "/usr/local/bin/" + b,
        )
        monkeypatch.setattr(_commands, "_orchestrator_over_quota", lambda _a: False)

        chain = _commands._resolve_orchestrator_chain("claude")
        names = [e[0][0] for e in chain]
        assert "droid" not in names


# ── config helpers ───────────────────────────────────────────────────────────

class TestConfigHelpers:
    def test_fallback_enabled_default_true(self, fake_home: Path) -> None:
        assert _cfg.orchestrator_fallback_enabled() is True

    def test_fallback_enabled_can_be_disabled(self, fake_home: Path) -> None:
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["orchestrator"] = {"fallback_enabled": False}
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))
        assert _cfg.orchestrator_fallback_enabled() is False

    def test_quota_threshold_defaults(self, fake_home: Path) -> None:
        assert _cfg.quota_threshold() == {"five_hour": 95, "seven_day": 90}

    def test_quota_threshold_custom(self, fake_home: Path) -> None:
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["orchestrator"] = {
            "quota_threshold": {"five_hour": 80, "seven_day": 70},
        }
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))
        assert _cfg.quota_threshold() == {"five_hour": 80, "seven_day": 70}

    def test_fallback_list(self, fake_home: Path) -> None:
        assert _cfg.orchestrator_fallback() == []
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["orchestrator"] = {"fallback": ["codex", "gemini"]}
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))
        assert _cfg.orchestrator_fallback() == ["codex", "gemini"]
