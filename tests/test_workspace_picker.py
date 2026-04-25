"""Tests for `central-mcp workspace use` interactive picker (no-arg form)."""

from __future__ import annotations

from pathlib import Path

import pytest

from central_mcp import config as _cfg
from central_mcp import registry
from central_mcp.cli import _commands


def _seed_workspaces(fake_home: Path) -> None:
    fake_home.mkdir(parents=True, exist_ok=True)
    registry.add_project("p1", "/tmp/p1")
    registry.add_project("p2", "/tmp/p2")
    registry.add_project("p3", "/tmp/p3")
    registry.add_workspace("work")
    registry.add_workspace("personal")
    registry.add_to_workspace("p1", "work")
    registry.add_to_workspace("p2", "work")
    registry.add_to_workspace("p3", "personal")


class TestPickWorkspaceInteractive:
    """`load_workspaces()` always carries the implicit `default`
    workspace alongside any user-created ones, so the sorted name list
    here is ["default", "personal", "work"]."""

    def test_returns_picked_name(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_workspaces(fake_home)
        captured: list[dict] = []
        def _fake(prompt, labels, default=0, *, description=None):
            captured.append({
                "prompt": prompt,
                "labels": labels,
                "default": default,
                "description": description,
            })
            return 2  # index 2 → "work"
        monkeypatch.setattr(_commands, "_arrow_select", _fake)
        picked = _commands._pick_workspace_interactive()
        assert picked == "work"
        assert captured[0]["prompt"] == "Switch workspace"
        assert captured[0]["description"] is not None
        # Labels carry workspace name + project count. Seeded:
        #   work     → p1, p2     (2 projects)
        #   personal → p3         (1 project)
        assert any("personal" in lbl and "1 project" in lbl
                   for lbl in captured[0]["labels"])
        assert any("work" in lbl and "2 projects" in lbl
                   for lbl in captured[0]["labels"])

    def test_default_index_points_at_active_workspace(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_workspaces(fake_home)
        _cfg.set_current_workspace("work")
        defaults: list[int] = []
        monkeypatch.setattr(
            _commands, "_arrow_select",
            lambda prompt, labels, default=0, *, description=None: defaults.append(default) or default,
        )
        _commands._pick_workspace_interactive()
        # Sorted names = ["default", "personal", "work"] → "work" at index 2.
        assert defaults == [2]

    def test_active_marker_appears_in_label(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_workspaces(fake_home)
        _cfg.set_current_workspace("personal")
        captured: list[list[str]] = []
        monkeypatch.setattr(
            _commands, "_arrow_select",
            lambda prompt, labels, default=0, *, description=None: captured.append(labels) or 0,
        )
        _commands._pick_workspace_interactive()
        labels = captured[0]
        active_label = next(lbl for lbl in labels if "personal" in lbl)
        other_label = next(lbl for lbl in labels if "work" in lbl)
        assert "[current]" in active_label
        assert "[current]" not in other_label


class TestWsUseInteractive:
    def test_no_arg_invokes_picker_and_switches(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_workspaces(fake_home)
        _cfg.set_current_workspace("personal")
        # Sorted names = ["default", "personal", "work"]; index 2 → "work"
        monkeypatch.setattr(_commands, "_arrow_select",
                            lambda *a, **kw: 2)

        rc = _commands._ws_use(None)
        assert rc == 0
        assert _cfg.current_workspace() == "work"

    def test_explicit_name_skips_picker(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_workspaces(fake_home)
        called = []
        monkeypatch.setattr(
            _commands, "_arrow_select",
            lambda *a, **kw: called.append(True) or 0,
        )
        rc = _commands._ws_use("work")
        assert rc == 0
        assert called == [], "picker must NOT run when name is supplied"
        assert _cfg.current_workspace() == "work"

    def test_unknown_explicit_name_returns_error(
        self, fake_home: Path
    ) -> None:
        _seed_workspaces(fake_home)
        rc = _commands._ws_use("does-not-exist")
        assert rc == 1
