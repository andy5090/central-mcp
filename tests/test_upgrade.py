"""Tests for `central-mcp upgrade` (self-update via PyPI)."""

from __future__ import annotations

import pytest

from central_mcp import upgrade


class TestParse:
    def test_basic_semver(self) -> None:
        assert upgrade._parse("0.2.0") == (0, 2, 0)

    def test_double_digit_minor_beats_single(self) -> None:
        # Regression: string compare wrongly orders 0.1.10 < 0.1.2.
        assert upgrade._parse("0.1.10") > upgrade._parse("0.1.2")

    def test_drops_pre_release_tail(self) -> None:
        # `0.2.0a1` is treated as 0.2.0 for upgrade-decision purposes.
        assert upgrade._parse("0.2.0a1") == (0, 2, 0)

    def test_shorter_prefix(self) -> None:
        assert upgrade._parse("1.0") < upgrade._parse("1.0.1")


class TestRun:
    def _patch_versions(self, monkeypatch, installed: str, latest: str) -> None:
        monkeypatch.setattr(upgrade, "installed_version", lambda: installed)
        monkeypatch.setattr(upgrade, "latest_version", lambda timeout=5.0: latest)

    def test_up_to_date(self, monkeypatch, capsys) -> None:
        self._patch_versions(monkeypatch, "0.2.0", "0.2.0")
        rc = upgrade.run(check_only=False)
        assert rc == 0
        assert "up to date" in capsys.readouterr().out

    def test_newer_version_check_only_does_not_install(
        self, monkeypatch, capsys
    ) -> None:
        self._patch_versions(monkeypatch, "0.1.0", "0.2.0")

        called = []
        monkeypatch.setattr(
            upgrade.subprocess, "call", lambda cmd: called.append(cmd) or 0
        )

        rc = upgrade.run(check_only=True)
        assert rc == 0
        assert called == []
        out = capsys.readouterr().out
        assert "0.1.0" in out and "0.2.0" in out
        assert "--check" in out

    def test_newer_version_runs_upgrade_command(
        self, monkeypatch
    ) -> None:
        self._patch_versions(monkeypatch, "0.1.0", "0.2.0")

        calls: list[list[str]] = []
        monkeypatch.setattr(
            upgrade.subprocess, "call", lambda cmd: calls.append(cmd) or 0
        )

        rc = upgrade.run(check_only=False)
        assert rc == 0
        assert len(calls) == 1
        cmd = calls[0]
        # Whichever installer was selected, the package must be named.
        assert upgrade.PACKAGE in cmd

    def test_not_installed_errors(self, monkeypatch) -> None:
        monkeypatch.setattr(upgrade, "installed_version", lambda: None)
        assert upgrade.run(check_only=False) == 1

    def test_pypi_unreachable_errors(self, monkeypatch) -> None:
        from urllib.error import URLError
        monkeypatch.setattr(upgrade, "installed_version", lambda: "0.2.0")

        def _boom(timeout=5.0):
            raise URLError("no net")

        monkeypatch.setattr(upgrade, "latest_version", _boom)
        assert upgrade.run(check_only=False) == 1
