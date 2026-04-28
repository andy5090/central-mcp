"""Tests for the user-level config (~/.central-mcp/config.toml).

Covers timezone resolution cascade, workspace persistence, and the
`ensure_initialized()` migration path that moves `current_workspace`
out of the legacy registry.yaml location.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from central_mcp import config
from central_mcp import paths
from central_mcp import registry


# ── timezone ──────────────────────────────────────────────────────────────────

class TestUserTimezone:
    def test_falls_back_to_system_when_missing(self, fake_home: Path) -> None:
        # No config.toml → falls back to system tz (varies by host, but
        # never empty and never raises).
        tz = config.user_timezone()
        assert isinstance(tz, str)
        assert tz

    def test_honors_configured_value(self, fake_home: Path) -> None:
        config.set_user_timezone("Asia/Seoul")
        assert config.user_timezone() == "Asia/Seoul"

    def test_tz_env_overrides_system_when_iana_like(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TZ", "Europe/Berlin")
        # No config file yet — _system_timezone picks it up from TZ.
        assert config._system_timezone() == "Europe/Berlin"

    def test_tz_env_non_iana_is_ignored_by_system_probe(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TZ", "EST")   # not IANA-style
        # Falls through to /etc/localtime or UTC — never blindly uses "EST".
        assert config._system_timezone() != "EST"


# ── current_workspace ─────────────────────────────────────────────────────────

class TestCurrentWorkspace:
    def test_no_config_returns_default(self, fake_home: Path) -> None:
        assert config.current_workspace() == "default"

    def test_set_with_existing_workspace(self, fake_home: Path) -> None:
        registry.add_project("p", "/p")
        registry.add_workspace("work")
        config.set_current_workspace("work")
        assert config.current_workspace() == "work"

    def test_set_default_when_no_workspaces_registered(
        self, fake_home: Path
    ) -> None:
        # Empty registry → any name is permitted (nothing to validate against).
        config.set_current_workspace("default")
        assert config.current_workspace() == "default"

    def test_set_unknown_workspace_raises(self, fake_home: Path) -> None:
        registry.add_project("p", "/p")   # seeds 'default' workspace
        with pytest.raises(ValueError, match="unknown workspace"):
            config.set_current_workspace("nonexistent")

    def test_env_var_overrides_saved_value(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Saved default in config.toml is "default"; env says "client-a".
        # Per-process env wins so multiple shells / MCP clients can
        # concurrently target different workspaces.
        registry.add_project("p", "/p")
        registry.add_workspace("client-a")
        config.set_current_workspace("default")
        monkeypatch.setenv("CMCP_WORKSPACE", "client-a")
        assert config.current_workspace() == "client-a"

    def test_env_var_used_even_when_unknown_to_registry(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # current_workspace() does NOT validate — that's set_current_workspace's
        # job. The env path is intentionally permissive: validation happens
        # at the CLI surface (cmcp run --workspace), not on every read.
        monkeypatch.setenv("CMCP_WORKSPACE", "made-up")
        assert config.current_workspace() == "made-up"

    def test_no_env_falls_through_to_config(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry.add_project("p", "/p")
        registry.add_workspace("work")
        config.set_current_workspace("work")
        monkeypatch.delenv("CMCP_WORKSPACE", raising=False)
        assert config.current_workspace() == "work"


# ── ensure_initialized() ──────────────────────────────────────────────────────

class TestEnsureInitialized:
    def test_creates_user_section_with_system_tz(self, fake_home: Path) -> None:
        assert not paths.config_file().exists()
        changed = config.ensure_initialized()
        assert changed is True
        assert paths.config_file().exists()

        doc = tomlkit.parse(paths.config_file().read_text())
        assert "user" in doc
        assert doc["user"]["timezone"]          # non-empty
        # 0.11.1+ stores the saved workspace as `last_workspace`; the
        # legacy `current_workspace` key MUST not appear on a fresh init.
        assert doc["user"]["last_workspace"] == "default"
        assert "current_workspace" not in doc["user"]

    def test_is_idempotent(self, fake_home: Path) -> None:
        config.ensure_initialized()
        # Second call changes nothing.
        assert config.ensure_initialized() is False

    def test_preserves_existing_user_values(self, fake_home: Path) -> None:
        config.set_user_timezone("Asia/Seoul")
        config.ensure_initialized()
        assert config.user_timezone() == "Asia/Seoul"

    def test_migrates_current_workspace_from_registry(
        self, fake_home: Path
    ) -> None:
        # Simulate a legacy registry where current_workspace lived.
        registry.add_project("p", "/p")           # creates registry + workspaces
        # Inject the legacy field directly (this is what old versions wrote).
        raw = registry._read_raw()
        raw["current_workspace"] = "work"
        raw.setdefault("workspaces", {})["work"] = []
        registry._write_raw(raw)

        config.ensure_initialized()

        # Config now carries the value under the new key…
        assert config.current_workspace() == "work"
        doc = tomlkit.parse(paths.config_file().read_text())
        assert doc["user"]["last_workspace"] == "work"
        # …and the legacy key is gone from registry.yaml.
        raw_after = registry._read_raw()
        assert "current_workspace" not in raw_after

    def test_migrates_current_workspace_in_config_to_last_workspace(
        self, fake_home: Path
    ) -> None:
        """0.10.0–0.11.0 stored the saved workspace under
        `[user].current_workspace`. Ensure that's renamed to
        `last_workspace` on next startup, with the value preserved."""
        # Hand-craft a pre-rename config.toml.
        paths.config_file().parent.mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(
            '[user]\ntimezone = "UTC"\ncurrent_workspace = "work"\n'
        )

        config.ensure_initialized()

        doc = tomlkit.parse(paths.config_file().read_text())
        assert doc["user"]["last_workspace"] == "work"
        assert "current_workspace" not in doc["user"]
        # Reading should also return the migrated value.
        assert config.current_workspace() == "work"

    def test_set_clears_legacy_current_workspace_key(
        self, fake_home: Path
    ) -> None:
        """`set_current_workspace` should write to `last_workspace` and
        wipe any leftover `current_workspace` key in one pass."""
        paths.config_file().parent.mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(
            '[user]\ntimezone = "UTC"\ncurrent_workspace = "old"\n'
        )
        registry.add_project("p", "/p")
        registry.add_workspace("new")

        config.set_current_workspace("new")

        doc = tomlkit.parse(paths.config_file().read_text())
        assert doc["user"]["last_workspace"] == "new"
        assert "current_workspace" not in doc["user"]
