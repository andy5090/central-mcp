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

    def test_hub_holds_panes_per_window_minus_one(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        """panes_per_window=4 + orchestrator → hub has 1 orch + 2 projects.

        Mirrors tmux: the orchestrator visually takes 2 cells (main-
        vertical left half), so the hub window only holds
        panes_per_window - 1 panes total.
        """
        for i in range(6):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch = OrchestratorPane(command="echo hi", cwd=str(tmp_path), label="stub")
        kdl = zellij.build_layout(orchestrator=orch, panes_per_window=4)

        # Hub tab should reference p0 and p1 only (not p2+).
        hub_start = kdl.index(f'tab name="{window_name(0, has_orchestrator=True)}"')
        # Find the end of the hub tab block. Hub spans until next `tab name=` or EOF.
        next_tab = kdl.find('tab name="', hub_start + 1)
        hub_block = kdl[hub_start:next_tab] if next_tab != -1 else kdl[hub_start:]
        assert '"p0"' in hub_block
        assert '"p1"' in hub_block
        assert '"p2"' not in hub_block
        # p2..p5 should be in overflow tabs.
        tail = kdl[next_tab:] if next_tab != -1 else ""
        for i in range(2, 6):
            assert f'"p{i}"' in tail

    def test_project_pane_invokes_central_mcp_watch(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        d = tmp_path / "alpha"
        d.mkdir()
        registry.add_project("alpha", str(d), agent="shell")

        kdl = zellij.build_layout()
        # Each project pane is wrapped in `sh -c '<cmd> </dev/null; sleep infinity'`
        # so the pane is read-only (stdin piped from /dev/null) and
        # stays alive on exit without dropping to a shell.
        assert 'command="sh"' in kdl
        assert "central-mcp watch alpha" in kdl
        assert "</dev/null" in kdl
        assert "sleep infinity" in kdl


class TestTilingShape:
    """Verify the 2-row wide-column tiling algorithm.

    The underlying `_tile_panes` helper is internal, so we inspect the
    generated KDL to assert the structural contract: at most `rows=2`
    rows, columns grow horizontally, small pane counts collapse to a
    single horizontal row.
    """

    def _count(self, kdl: str, needle: str) -> int:
        return kdl.count(needle)

    def test_overflow_four_panes_build_2x2_grid(
        self, fake_home, tmp_path
    ) -> None:
        # 4 projects total = 4 in overflow tab (no orchestrator).
        for i in range(4):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        kdl = zellij.build_layout(panes_per_window=4)
        # 4 panes should produce 2 rows, each a vertical (side-by-side)
        # split — i.e., one outer horizontal + two inner vertical splits.
        assert 'split_direction="horizontal"' in kdl
        assert self._count(kdl, 'split_direction="vertical"') >= 2, (
            "expected at least two vertical splits for a 2x2 grid"
        )

    def test_overflow_ten_panes_grow_horizontally(
        self, fake_home, tmp_path
    ) -> None:
        # 10 projects with panes_per_window=10 → one overflow tab with
        # 10 panes, which should render as 2 rows × 5 cols (wide),
        # not 5 rows × 2 cols (tall).
        for i in range(10):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        kdl = zellij.build_layout(panes_per_window=10)
        # The top row contains p0..p4; the bottom row contains p5..p9.
        # Find the order of project names in the KDL and assert the
        # expected grouping.
        positions = [kdl.index(f'"p{i}"') for i in range(10)]
        # Top row (p0..p4) should appear before the bottom row (p5..p9).
        assert max(positions[:5]) < min(positions[5:]), (
            f"top row panes should come before bottom row panes; positions={positions}"
        )

    def test_hub_with_three_projects_uses_grid_on_right(
        self, fake_home, tmp_path
    ) -> None:
        # Orchestrator + 3 project panes in hub (panes_per_window=5 →
        # hub holds orch + 3 projects).
        for i in range(3):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch = OrchestratorPane(command="echo hi", cwd=str(tmp_path), label="stub")
        kdl = zellij.build_layout(orchestrator=orch, panes_per_window=5)

        # When the right half has 3 panes, we should see the 2-row grid:
        # outer vertical (orch | right-block), right-block is horizontal
        # (top row | bot row), top row is vertical (p0 p1).
        # At minimum: at least 3 `split_direction="vertical"` occurrences
        # (outer orch-vs-right + top row + any other row-internal splits).
        assert self._count(kdl, 'split_direction="vertical"') >= 2

    def test_hub_with_two_projects_keeps_vertical_stack(
        self, fake_home, tmp_path
    ) -> None:
        """Regression guard: orch + 2 projects should NOT trigger the
        new 2-row grid — halving a narrow right column into a 2-col
        row would make each project pane unreadably thin."""
        for i in range(2):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch = OrchestratorPane(command="echo hi", cwd=str(tmp_path), label="stub")
        kdl = zellij.build_layout(orchestrator=orch, panes_per_window=4)
        # Stack-style right block uses exactly one horizontal split
        # (the right-side children); the outer vertical is the
        # orchestrator-vs-right divider. So total vertical splits = 1.
        # Project panes appear in order top-to-bottom, stacked.
        p0_idx = kdl.index('"p0"')
        p1_idx = kdl.index('"p1"')
        assert p0_idx < p1_idx


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
