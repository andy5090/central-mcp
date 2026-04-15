from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit

from central_mcp import install


@pytest.fixture
def fake_codex_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point $HOME at a temp dir so codex config writes never touch real files."""
    home = tmp_path / "home"
    home.mkdir()
    codex_dir = home / ".codex"
    codex_dir.mkdir()
    cfg = codex_dir / "config.toml"
    cfg.write_text(
        '[mcp_servers.other]\n'
        'command = "other-binary"\n'
        'args = ["serve"]\n'
    )
    monkeypatch.setenv("HOME", str(home))
    return cfg


def test_install_codex_adds_entry(fake_codex_config: Path) -> None:
    rc = install.install("codex")
    assert rc == 0
    data = tomlkit.parse(fake_codex_config.read_text())
    assert "central" in data["mcp_servers"]
    entry = data["mcp_servers"]["central"]
    assert entry["command"] == "central-mcp"
    assert list(entry["args"]) == ["serve"]
    # Preserves the pre-existing server
    assert "other" in data["mcp_servers"]


def test_install_codex_is_idempotent(fake_codex_config: Path) -> None:
    assert install.install("codex") == 0
    # Second call — must not change content (no new backup either).
    assert install.install("codex") == 0
    data = tomlkit.parse(fake_codex_config.read_text())
    assert data["mcp_servers"]["central"]["command"] == "central-mcp"


def test_install_codex_refuses_if_no_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # No ~/.codex/config.toml at all
    rc = install.install("codex")
    assert rc == 1


def test_install_cursor_creates_mcp_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    rc = install.install("cursor")
    assert rc == 0
    data = json.loads((home / ".cursor" / "mcp.json").read_text())
    assert data["mcpServers"]["central"]["command"] == "central-mcp"
    assert data["mcpServers"]["central"]["args"] == ["serve"]


def test_install_cursor_merges_with_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".cursor").mkdir()
    existing = {
        "mcpServers": {
            "preexisting": {"command": "x", "args": []}
        }
    }
    (home / ".cursor" / "mcp.json").write_text(json.dumps(existing))
    monkeypatch.setenv("HOME", str(home))
    assert install.install("cursor") == 0
    data = json.loads((home / ".cursor" / "mcp.json").read_text())
    assert "preexisting" in data["mcpServers"]
    assert "central" in data["mcpServers"]


def test_install_cursor_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert install.install("cursor") == 0
    assert install.install("cursor") == 0
