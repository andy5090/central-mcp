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


@pytest.fixture
def fake_gemini_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point $HOME at a temp dir with a pre-existing ~/.gemini/settings.json."""
    home = tmp_path / "home"
    home.mkdir()
    gemini_dir = home / ".gemini"
    gemini_dir.mkdir()
    cfg = gemini_dir / "settings.json"
    cfg.write_text(
        json.dumps(
            {
                "selectedAuthType": "gemini-api-key",
                "mcpServers": {
                    "other": {"command": "other-binary", "args": ["serve"]}
                },
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    return cfg


def test_install_gemini_adds_entry(fake_gemini_config: Path) -> None:
    rc = install.install("gemini")
    assert rc == 0
    data = json.loads(fake_gemini_config.read_text())
    assert "central" in data["mcpServers"]
    assert data["mcpServers"]["central"]["command"] == "central-mcp"
    assert data["mcpServers"]["central"]["args"] == ["serve"]
    # Preserves unrelated settings and pre-existing servers
    assert data["selectedAuthType"] == "gemini-api-key"
    assert "other" in data["mcpServers"]


def test_install_gemini_is_idempotent(fake_gemini_config: Path) -> None:
    assert install.install("gemini") == 0
    first = fake_gemini_config.read_text()
    assert install.install("gemini") == 0
    # File content must be byte-identical on the second (idempotent) run.
    second = fake_gemini_config.read_text()
    assert first == second


def test_install_gemini_creates_config_if_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlike codex (which requires a pre-existing config file), gemini
    install should bootstrap an empty ~/.gemini/settings.json — useful
    for freshly installed Gemini CLIs the user hasn't opened yet."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    rc = install.install("gemini")
    assert rc == 0
    cfg = home / ".gemini" / "settings.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["central"]["command"] == "central-mcp"


def test_install_gemini_rejects_non_object_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    (home / ".gemini" / "settings.json").write_text('["not", "an", "object"]')
    monkeypatch.setenv("HOME", str(home))
    assert install.install("gemini") == 1


def test_install_gemini_rejects_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".gemini").mkdir(parents=True)
    (home / ".gemini" / "settings.json").write_text("{not json")
    monkeypatch.setenv("HOME", str(home))
    assert install.install("gemini") == 1


# ---------------------------------------------------------------------------
# opencode
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_opencode_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point $HOME at a temp dir with a pre-existing opencode config."""
    home = tmp_path / "home"
    home.mkdir()
    cfg_dir = home / ".config" / "opencode"
    cfg_dir.mkdir(parents=True)
    cfg = cfg_dir / "opencode.json"
    cfg.write_text(
        json.dumps(
            {
                "mcp": {
                    "other": {"type": "local", "command": ["other-binary"]}
                },
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    return cfg


def test_install_opencode_adds_entry(fake_opencode_config: Path) -> None:
    rc = install.install("opencode")
    assert rc == 0
    data = json.loads(fake_opencode_config.read_text())
    assert "central" in data["mcp"]
    assert data["mcp"]["central"]["type"] == "local"
    assert data["mcp"]["central"]["command"] == ["central-mcp", "serve"]
    assert "other" in data["mcp"]


def test_install_opencode_is_idempotent(fake_opencode_config: Path) -> None:
    assert install.install("opencode") == 0
    first = fake_opencode_config.read_text()
    assert install.install("opencode") == 0
    assert fake_opencode_config.read_text() == first


def test_install_opencode_creates_config_if_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    rc = install.install("opencode")
    assert rc == 0
    cfg = home / ".config" / "opencode" / "opencode.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text())
    assert data["mcp"]["central"]["command"] == ["central-mcp", "serve"]


def test_install_opencode_rejects_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.json").write_text("{not json")
    monkeypatch.setenv("HOME", str(home))
    assert install.install("opencode") == 1

