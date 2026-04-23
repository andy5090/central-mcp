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
        assert doc["user"]["current_workspace"] == "default"

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

        # Config now carries the value…
        assert config.current_workspace() == "work"
        # …and the legacy key is gone from registry.yaml.
        raw_after = registry._read_raw()
        assert "current_workspace" not in raw_after
