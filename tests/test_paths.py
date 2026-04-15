from __future__ import annotations

from pathlib import Path

import pytest

from central_mcp import paths


def test_home_defaults_to_dot_central_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CENTRAL_MCP_HOME", raising=False)
    assert paths.central_mcp_home() == (Path.home() / ".central-mcp").resolve()


def test_home_honors_env_override(fake_home: Path) -> None:
    assert paths.central_mcp_home() == fake_home.resolve()


def test_log_and_config_under_home(fake_home: Path) -> None:
    assert paths.log_root() == fake_home.resolve() / "logs"
    assert paths.config_file() == fake_home.resolve() / "config.toml"
    assert paths.project_log_path("foo") == fake_home.resolve() / "logs" / "foo" / "pane.log"


def test_registry_cascade_prefers_env(
    tmp_path: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "custom-registry.yaml"
    monkeypatch.setenv("CENTRAL_MCP_REGISTRY", str(custom))
    assert paths.registry_path() == custom.resolve()


def test_registry_cascade_uses_cwd_if_present(
    tmp_path: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "work-with-registry"
    cwd.mkdir()
    (cwd / "registry.yaml").write_text("projects: []\n")
    monkeypatch.chdir(cwd)
    assert paths.registry_path() == (cwd / "registry.yaml").resolve()


def test_registry_cascade_falls_back_to_home(fake_home: Path) -> None:
    # fake_home fixture puts us in an empty cwd and unsets CENTRAL_MCP_REGISTRY.
    assert paths.registry_path() == fake_home.resolve() / "registry.yaml"
