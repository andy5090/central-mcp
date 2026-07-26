"""Which projects get an observation pane.

Pure selection policy — no tmux or zellij required, so these run
everywhere (unlike `test_layout.py`, which drives real tmux sessions).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pytest

from central_mcp import events, registry
from central_mcp.cli._commands import _select_observation_projects


def _args(**kwargs: object) -> argparse.Namespace:
    base = {"projects": None, "all_projects": False}
    base.update(kwargs)
    return argparse.Namespace(**base)


def _projects(*names: str) -> list[registry.Project]:
    return [registry.Project(name=n, path=f"/tmp/{n}", agent="hermes") for n in names]


class TestExplicitSelection:
    def test_named_projects_win_in_the_order_given(self, fake_home: Path) -> None:
        projs = _projects("a", "b", "c", "d")
        selected, notes = _select_observation_projects(projs, _args(projects="c,a"), 2)
        assert [p.name for p in selected] == ["c", "a"]
        assert notes == []

    def test_explicit_selection_ignores_the_pane_budget(self, fake_home: Path) -> None:
        """If the user names five projects, they asked for five panes."""
        projs = _projects("a", "b", "c", "d", "e")
        selected, _ = _select_observation_projects(
            projs, _args(projects="a,b,c,d,e"), 2
        )
        assert len(selected) == 5

    def test_unknown_name_warns_and_is_skipped(self, fake_home: Path) -> None:
        projs = _projects("a", "b")
        selected, notes = _select_observation_projects(projs, _args(projects="a,ghost"), 4)
        assert [p.name for p in selected] == ["a"]
        assert any("ghost" in n for n in notes)

    def test_whitespace_and_empties_are_tolerated(self, fake_home: Path) -> None:
        projs = _projects("a", "b")
        selected, _ = _select_observation_projects(projs, _args(projects=" a , , b "), 4)
        assert [p.name for p in selected] == ["a", "b"]


class TestDefaultSelection:
    def test_everything_shows_when_it_fits_one_window(self, fake_home: Path) -> None:
        """Small portfolios behave exactly as before — no focus, no notes."""
        projs = _projects("a", "b", "c")
        selected, notes = _select_observation_projects(projs, _args(), 4)
        assert [p.name for p in selected] == ["a", "b", "c"]
        assert notes == []

    def test_exactly_at_the_budget_still_shows_everything(self, fake_home: Path) -> None:
        projs = _projects("a", "b", "c", "d")
        selected, notes = _select_observation_projects(projs, _args(), 4)
        assert len(selected) == 4
        assert notes == []

    def test_overflow_falls_back_to_most_recently_active(self, fake_home: Path) -> None:
        projs = _projects("a", "b", "c", "d", "e")
        # Only c and e have any recorded activity; c is older than e.
        # Event timestamps are millisecond-precision and these land in
        # different files, so nudge them apart — identical stamps fall
        # back to registry order, which would put c first legitimately.
        events.log_event("c", "d1", "complete", ok=True)
        time.sleep(0.005)
        events.log_event("e", "d1", "complete", ok=True)

        selected, notes = _select_observation_projects(projs, _args(), 2)
        assert [p.name for p in selected] == ["e", "c"]
        assert notes

    def test_overflow_names_what_it_dropped(self, fake_home: Path) -> None:
        """A silently truncated grid reads as 'this is everything'."""
        projs = _projects("a", "b", "c")
        selected, notes = _select_observation_projects(projs, _args(), 1)
        joined = " ".join(notes)
        dropped = [p.name for p in projs if p not in selected]
        for name in dropped:
            assert name in joined
        assert "--all-projects" in joined
        assert "pulse" in joined

    def test_all_projects_flag_restores_full_tiling(self, fake_home: Path) -> None:
        projs = _projects("a", "b", "c", "d", "e")
        selected, notes = _select_observation_projects(
            projs, _args(all_projects=True), 2
        )
        assert [p.name for p in selected] == ["a", "b", "c", "d", "e"]
        assert notes == []

    def test_empty_registry(self, fake_home: Path) -> None:
        selected, notes = _select_observation_projects([], _args(), 4)
        assert selected == []
        assert notes == []


class TestSwitchSubcommandCompatibility:
    def test_namespace_without_focus_attrs_uses_defaults(self, fake_home: Path) -> None:
        """`tmux switch` / `zellij switch` don't define the focus flags."""
        projs = _projects("a", "b")
        selected, notes = _select_observation_projects(projs, argparse.Namespace(), 4)
        assert len(selected) == 2
        assert notes == []
