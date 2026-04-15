"""Shared fixtures — isolate every test from the real `~/.central-mcp`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CENTRAL_MCP_HOME at a throwaway directory.

    Tests that touch registries, configs, or log paths should request
    this fixture so they never read or write the user's real state.
    """
    home = tmp_path / "central-mcp-home"
    monkeypatch.setenv("CENTRAL_MCP_HOME", str(home))
    # Also scrub CENTRAL_MCP_REGISTRY so the cascade's first level doesn't
    # point at an unrelated leftover from the host environment.
    monkeypatch.delenv("CENTRAL_MCP_REGISTRY", raising=False)
    # And move cwd somewhere that has no registry.yaml, so the second
    # level of the cascade doesn't accidentally fire.
    empty_cwd = tmp_path / "cwd-with-no-registry"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    return home
