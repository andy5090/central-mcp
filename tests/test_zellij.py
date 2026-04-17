"""Tests for the Zellij observation backend.

Unit tests exercise the KDL layout generation (pure function, no
subprocess). The module's session helpers (`has_session`, `kill_session`,
etc.) require a real zellij binary and aren't covered here — those
are reserved for a live test once a zellij-equivalent of tmux live
testing infrastructure is in place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from central_mcp import registry, zellij
from central_mcp.layout import OrchestratorPane, window_name, HUB_SUFFIX


class TestBuildLayout:
    def test_empty_registry_produces_single_placeholder_tab(
        self, fake_home: Path
    ) -> None:
        kdl = zellij.build_layout()
        assert kdl.startswith("layout {")
        assert kdl.rstrip().endswith("}")
        assert "cmcp-1" in kdl

    def test_orchestrator_tab_has_hub_suffix(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        d = tmp_path / "proj"
        d.mkdir()
        registry.add_project("proj", str(d), agent="shell")

        orch = OrchestratorPane(command="echo hi", cwd=str(tmp_path), label="stub")
        kdl = zellij.build_layout(orchestrator=orch)
        assert f'tab name="{window_name(0, has_orchestrator=True)}"' in kdl
        assert HUB_SUFFIX in kdl
        assert "Central MCP Orchestrator" in kdl
        assert "proj" in kdl

    def test_hub_uses_vertical_split_and_right_horizontal_stack(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        for i in range(2):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch = OrchestratorPane(command="echo hi", cwd=str(tmp_path), label="stub")
        kdl = zellij.build_layout(orchestrator=orch)
        # Hub tab splits left/right, right side stacks projects vertically
        # (zellij's "horizontal" split direction = left/right visually in
        # their model — but we specifically want the orchestrator on the
        # outer vertical split and projects stacked via a nested split).
        assert 'split_direction="vertical"' in kdl
        assert 'split_direction="horizontal"' in kdl

    def test_overflow_tabs_follow_cmcp_n_naming(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        # 1 orch + 6 projects = 1 orch + 2 in hub + 4 in overflow tab (panes_per_window=4).
        for i in range(6):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch = OrchestratorPane(command="echo hi", cwd=str(tmp_path), label="stub")
        kdl = zellij.build_layout(orchestrator=orch)
        assert f'tab name="{window_name(0, has_orchestrator=True)}"' in kdl
        assert f'tab name="{window_name(1, has_orchestrator=True)}"' in kdl

    def test_no_orchestrator_uses_plain_cmcp_1(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        for i in range(3):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        kdl = zellij.build_layout()
        assert f'tab name="{window_name(0)}"' in kdl
        assert HUB_SUFFIX not in kdl

    def test_invalid_panes_per_window_rejected(self, fake_home: Path) -> None:
        with pytest.raises(ValueError, match="panes_per_window"):
            zellij.build_layout(panes_per_window=0)

    def test_project_pane_invokes_central_mcp_watch(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        d = tmp_path / "alpha"
        d.mkdir()
        registry.add_project("alpha", str(d), agent="shell")

        kdl = zellij.build_layout()
        # Each project pane must launch `central-mcp watch <project>`.
        assert 'command="central-mcp"' in kdl
        assert '"watch"' in kdl
        assert '"alpha"' in kdl


class TestWriteLayout:
    def test_creates_parent_and_writes_kdl(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "nested" / "layout.kdl"
        assert not target.exists()
        path = zellij.write_layout(target)
        assert path == target
        assert target.exists()
        body = target.read_text()
        assert body.startswith("layout {")
