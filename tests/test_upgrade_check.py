"""Tests for startup-time upgrade probe (_maybe_prompt_upgrade) and the
color-aware arrow picker it uses.
"""

from __future__ import annotations

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


# ── _maybe_prompt_upgrade — skip + always-probe ──────────────────────────────

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

    def test_probes_on_every_call(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No interval gating — every interactive `central-mcp run`
        contacts PyPI. Cheap (2s timeout, silent on failure)."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)

        calls = []
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: calls.append(True) or None)
        for _ in range(3):
            _commands._maybe_prompt_upgrade()
        assert calls == [True, True, True]

    def test_no_picker_when_already_latest(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: None)
        picker_calls = []
        monkeypatch.setattr(_commands, "_arrow_select",
                            lambda *a, **kw: picker_calls.append(True) or 0)
        _commands._maybe_prompt_upgrade()
        assert picker_calls == [], "picker only shows when an upgrade exists"

    def test_declined_prompt_does_not_raise(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: ("0.10.5", "0.10.6"))
        # Picker returns "Skip" (index 1).
        picker_calls: list[dict] = []
        def _fake_picker(prompt, labels, default=0, *, description=None):
            picker_calls.append({
                "prompt": prompt,
                "labels": labels,
                "description": description,
            })
            return 1  # Skip
        monkeypatch.setattr(_commands, "_arrow_select", _fake_picker)

        ran_upgrade = []
        monkeypatch.setattr(upgrade, "run",
                            lambda **kw: ran_upgrade.append(True) or 0)
        # Must not raise SystemExit or call upgrade.run.
        _commands._maybe_prompt_upgrade()
        assert ran_upgrade == []
        assert picker_calls and picker_calls[0]["labels"] == ["Upgrade now", "Skip"]
        # The config-silence guidance now lives on the description sub-line,
        # not in the prompt itself.
        assert picker_calls[0]["description"] is not None
        assert "upgrade_check_enabled" in picker_calls[0]["description"]
        assert "0.10.6" in picker_calls[0]["prompt"]
        assert "0.10.5" in picker_calls[0]["prompt"]
        # Prompt line stays clean — no inline silence hint.
        assert "config.toml" not in picker_calls[0]["prompt"]

    def test_accepted_prompt_runs_upgrade_and_exits(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setattr(upgrade, "check_available_silent",
                            lambda *a, **kw: ("0.10.5", "0.10.6"))
        monkeypatch.setattr(_commands, "_arrow_select",
                            lambda *a, **kw: 0)  # "Upgrade now"

        ran_upgrade = []
        monkeypatch.setattr(upgrade, "run",
                            lambda **kw: ran_upgrade.append(True) or 0)
        with pytest.raises(SystemExit) as exc:
            _commands._maybe_prompt_upgrade()
        assert exc.value.code == 0
        assert ran_upgrade == [True]


# ── color helpers (_color_enabled / _Palette) ────────────────────────────────

class TestColorHelpers:
    def test_color_disabled_when_not_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        assert _commands._color_enabled() is False

    def test_color_disabled_when_NO_COLOR_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert _commands._color_enabled() is False

    def test_color_enabled_on_tty_without_NO_COLOR(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        assert _commands._color_enabled() is True

    def test_palette_when_enabled(self) -> None:
        pal = _commands._Palette(True)
        assert pal.bold == "\x1b[1m"
        assert pal.dim == "\x1b[2m"
        assert pal.cyan == "\x1b[36m"
        assert pal.reset == "\x1b[0m"

    def test_palette_when_disabled_yields_empty_strings(self) -> None:
        pal = _commands._Palette(False)
        assert pal.bold == ""
        assert pal.dim == ""
        assert pal.cyan == ""
        assert pal.reset == ""
