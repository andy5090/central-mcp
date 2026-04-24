"""Tests for startup-time upgrade probe (_maybe_prompt_upgrade)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from central_mcp import config as _cfg
from central_mcp import upgrade
from central_mcp.cli import _commands


# ── upgrade.check_available_silent ───────────────────────────────────────────

class TestCheckAvailableSilent:
    def test_none_when_latest_matches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(upgrade, "installed_version", lambda: "0.10.5")
        monkeypatch.setattr(upgrade, "latest_version", lambda timeout=5.0: "0.10.5")
        assert upgrade.check_available_silent() is None

    def test_returns_pair_when_newer_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(upgrade, "installed_version", lambda: "0.10.5")
        monkeypatch.setattr(upgrade, "latest_version", lambda timeout=5.0: "0.10.6")
        assert upgrade.check_available_silent() == ("0.10.5", "0.10.6")

    def test_none_when_pypi_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(upgrade, "installed_version", lambda: "0.10.5")
        def _boom(*a, **kw):
            raise RuntimeError("network down")
        monkeypatch.setattr(upgrade, "latest_version", _boom)
        assert upgrade.check_available_silent() is None

    def test_none_when_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(upgrade, "installed_version", lambda: None)
        assert upgrade.check_available_silent() is None


# ── config helpers ───────────────────────────────────────────────────────────

class TestConfigHelpers:
    def test_upgrade_check_enabled_default_true(self, fake_home: Path) -> None:
        assert _cfg.upgrade_check_enabled() is True

    def test_upgrade_check_enabled_off(self, fake_home: Path) -> None:
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["user"] = {"upgrade_check_enabled": False}
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))
        assert _cfg.upgrade_check_enabled() is False

    def test_interval_default(self, fake_home: Path) -> None:
        assert _cfg.upgrade_check_interval_hours() == 24

    def test_interval_custom(self, fake_home: Path) -> None:
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["user"] = {"upgrade_check_interval_hours": 6}
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))
        assert _cfg.upgrade_check_interval_hours() == 6

    def test_last_checked_roundtrip(self, fake_home: Path) -> None:
        assert _cfg.upgrade_last_checked_at() is None
        ts = "2026-04-24T10:00:00+00:00"
        _cfg.set_upgrade_last_checked_at(ts)
        assert _cfg.upgrade_last_checked_at() == ts


# ── _maybe_prompt_upgrade — skip paths ───────────────────────────────────────

class TestMaybePromptUpgrade:
    def test_skip_when_disabled(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tomlkit
        from central_mcp import paths
        doc = tomlkit.document()
        doc["user"] = {"upgrade_check_enabled": False}
        paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
        paths.config_file().write_text(tomlkit.dumps(doc))

        called = []
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: called.append(True) or None)
        _commands._maybe_prompt_upgrade()
        assert called == [], "check should NOT have run when disabled"

    def test_skip_when_non_tty(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        called = []
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: called.append(True) or None)
        _commands._maybe_prompt_upgrade()
        assert called == [], "check should skip in non-TTY"

    def test_skip_when_recently_checked(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pretend we checked 1 hour ago with 24h interval.
        fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(
            timespec="seconds"
        )
        _cfg.set_upgrade_last_checked_at(fresh)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)

        called = []
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: called.append(True) or None)
        _commands._maybe_prompt_upgrade()
        assert called == [], "recent check should gate next probe"

    def test_probe_runs_after_interval(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(
            timespec="seconds"
        )
        _cfg.set_upgrade_last_checked_at(stale)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)

        called = []
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: called.append(True) or None)
        _commands._maybe_prompt_upgrade()
        assert called == [True]
        # last_checked_at updated to "now"
        last = _cfg.upgrade_last_checked_at()
        assert last is not None and last > stale

    def test_declined_prompt_does_not_raise(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: ("0.10.5", "0.10.6"))
        # User types "n"
        monkeypatch.setattr("builtins.input", lambda: "n")

        ran_upgrade = []
        monkeypatch.setattr(upgrade, "run",
                            lambda **kw: ran_upgrade.append(True) or 0)
        # Must not raise SystemExit or call upgrade.run.
        _commands._maybe_prompt_upgrade()
        assert ran_upgrade == []
