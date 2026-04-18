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
    assert proj.path == "/tmp/test-proj"
    assert proj.agent == "claude"

    loaded = registry.load_registry()
    assert len(loaded) == 1
    assert loaded[0].name == "test-proj"
    assert loaded[0].agent == "claude"
    assert loaded[0].tags == ["a", "b"]
    assert loaded[0].description == "hello"


def test_add_preserves_insertion_order(fake_home: Path) -> None:
    registry.add_project("one", "/tmp/one")
    registry.add_project("two", "/tmp/two")
    registry.add_project("three", "/tmp/three")
    loaded = registry.load_registry()
    assert [p.name for p in loaded] == ["one", "two", "three"]


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


def test_add_default_agent_is_claude(fake_home: Path) -> None:
    proj = registry.add_project("p", "/p")
    assert proj.agent == "claude"


def test_write_creates_parent_dir(fake_home: Path) -> None:
    # fake_home doesn't exist yet; first write must mkdir -p.
    assert not fake_home.exists()
    registry.add_project("first", "/tmp/first")
    assert (fake_home / "registry.yaml").exists()


def test_update_project_agent_only(fake_home: Path) -> None:
    registry.add_project("p", "/p", agent="claude", description="d", tags=["x"])
    updated = registry.update_project("p", agent="codex")
    assert updated is not None
    assert updated.agent == "codex"
    assert updated.description == "d"
    assert updated.tags == ["x"]


def test_update_project_partial_preserves_other_fields(fake_home: Path) -> None:
    registry.add_project(
        "p", "/p", agent="claude", description="original", tags=["a"]
    )
    registry.update_project("p", permission_mode="bypass")
    loaded = registry.find_project("p")
    assert loaded is not None
    assert loaded.agent == "claude"
    assert loaded.description == "original"
    assert loaded.tags == ["a"]
    assert loaded.permission_mode == "bypass"


def test_update_project_rejects_invalid_permission_mode(fake_home: Path) -> None:
    registry.add_project("p", "/p")
    with pytest.raises(ValueError, match="invalid permission_mode"):
        registry.update_project("p", permission_mode="yolo")


def test_permission_mode_roundtrip(fake_home: Path) -> None:
    registry.add_project("p", "/p")
    registry.update_project("p", permission_mode="auto")
    reloaded = registry.load_registry()
    assert reloaded[0].permission_mode == "auto"


def test_update_project_fallback(fake_home: Path) -> None:
    registry.add_project("p", "/p", agent="claude")
    updated = registry.update_project("p", fallback=["codex", "gemini"])
    assert updated is not None
    assert updated.fallback == ["codex", "gemini"]
    loaded = registry.find_project("p")
    assert loaded.fallback == ["codex", "gemini"]


def test_update_project_missing_returns_none(fake_home: Path) -> None:
    assert registry.update_project("ghost", agent="codex") is None


def test_fallback_roundtrip_in_yaml(fake_home: Path) -> None:
    registry.add_project("p", "/p")
    registry.update_project("p", fallback=["codex"])
    reloaded = registry.load_registry()
    assert reloaded[0].fallback == ["codex"]
