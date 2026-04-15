from __future__ import annotations

from pathlib import Path

import pytest

from central_mcp import registry


def test_load_missing_file_returns_empty(fake_home: Path) -> None:
    assert registry.load_registry() == []


def test_add_then_load_round_trip(fake_home: Path) -> None:
    proj = registry.add_project(
        name="test-proj",
        path_="/tmp/test-proj",
        agent="claude",
        description="hello",
        tags=["a", "b"],
    )
    assert proj.name == "test-proj"
    assert proj.tmux.session == "central"
    assert proj.tmux.window == "projects"
    assert proj.tmux.pane == 0

    loaded = registry.load_registry()
    assert len(loaded) == 1
    assert loaded[0].name == "test-proj"
    assert loaded[0].agent == "claude"
    assert loaded[0].tags == ["a", "b"]


def test_add_auto_increments_pane(fake_home: Path) -> None:
    registry.add_project("one", "/tmp/one")
    registry.add_project("two", "/tmp/two")
    registry.add_project("three", "/tmp/three")
    loaded = registry.load_registry()
    assert [p.tmux.pane for p in loaded] == [0, 1, 2]


def test_add_duplicate_raises(fake_home: Path) -> None:
    registry.add_project("dup", "/tmp/dup")
    with pytest.raises(ValueError, match="already exists"):
        registry.add_project("dup", "/tmp/dup2")


def test_remove_project(fake_home: Path) -> None:
    registry.add_project("keep", "/tmp/keep")
    registry.add_project("drop", "/tmp/drop")
    assert registry.remove_project("drop") is True
    assert [p.name for p in registry.load_registry()] == ["keep"]


def test_remove_missing_returns_false(fake_home: Path) -> None:
    assert registry.remove_project("nothing") is False


def test_find_project(fake_home: Path) -> None:
    registry.add_project("alpha", "/a")
    found = registry.find_project("alpha")
    assert found is not None and found.path == "/a"
    assert registry.find_project("missing") is None


def test_projects_by_session_groups(fake_home: Path) -> None:
    registry.add_project("a", "/a", session="central")
    registry.add_project("b", "/b", session="work")
    registry.add_project("c", "/c", session="central")
    groups = registry.projects_by_session()
    assert sorted(groups.keys()) == ["central", "work"]
    assert [p.name for p in groups["central"]] == ["a", "c"]
    assert [p.name for p in groups["work"]] == ["b"]


def test_write_creates_parent_dir(fake_home: Path) -> None:
    # fake_home doesn't exist yet; first write must mkdir -p.
    assert not fake_home.exists()
    registry.add_project("first", "/tmp/first")
    assert (fake_home / "registry.yaml").exists()
