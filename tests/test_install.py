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


# ─── hermes ────────────────────────────────────────────────────────────


@pytest.fixture
def fake_hermes_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed `$HOME/.hermes/config.yaml` with a minimal user-edited config.

    Includes a comment + a pre-existing `mcp_servers.other` entry so the
    test can verify both round-trip preservation and merge behavior.
    """
    home = tmp_path / "home"
    home.mkdir()
    hermes_dir = home / ".hermes"
    hermes_dir.mkdir()
    cfg = hermes_dir / "config.yaml"
    cfg.write_text(
        "# user comment that must round-trip\n"
        "model:\n"
        "  default: gpt-5\n"
        "mcp_servers:\n"
        "  other:\n"
        "    command: other-binary\n"
        "    args:\n"
        "      - serve\n"
    )
    monkeypatch.setenv("HOME", str(home))
    return cfg


def test_install_hermes_adds_entry(fake_hermes_config: Path) -> None:
    from ruamel.yaml import YAML

    rc = install.install("hermes")
    assert rc == 0
    yaml = YAML()
    with fake_hermes_config.open("r") as fh:
        data = yaml.load(fh)
    assert "central" in data["mcp_servers"]
    entry = data["mcp_servers"]["central"]
    assert entry["command"] == "central-mcp"
    assert list(entry["args"]) == ["serve"]
    # Preserves the pre-existing server entry.
    assert "other" in data["mcp_servers"]
    # Round-trips the leading comment.
    assert "user comment that must round-trip" in fake_hermes_config.read_text()


def test_install_hermes_is_idempotent(fake_hermes_config: Path) -> None:
    assert install.install("hermes") == 0
    # Second call must be a no-op (no content drift).
    text_before = fake_hermes_config.read_text()
    assert install.install("hermes") == 0
    assert fake_hermes_config.read_text() == text_before


def test_install_hermes_refuses_if_no_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # No ~/.hermes/config.yaml — Hermes hasn't been initialized. We
    # don't fabricate the file because Hermes seeds many other defaults
    # during its own setup that we shouldn't try to mirror.
    assert install.install("hermes") == 1


def test_install_hermes_dry_run_does_not_write(fake_hermes_config: Path) -> None:
    text_before = fake_hermes_config.read_text()
    rc = install.install("hermes", dry_run=True)
    assert rc == 0
    assert fake_hermes_config.read_text() == text_before


def _skill_path(cfg: Path) -> Path:
    # fake_hermes_config yields <home>/.hermes/config.yaml
    return (
        cfg.parent / "skills" / "autonomous-ai-agents" / "central-mcp"
        / "SKILL.md"
    )


def test_install_hermes_writes_skill(fake_hermes_config: Path) -> None:
    assert install.install("hermes") == 0
    skill = _skill_path(fake_hermes_config)
    assert skill.exists()
    text = skill.read_text()
    # Frontmatter must carry the skill's registry identity.
    assert "name: central-mcp" in text
    # Core workflow guidance the skill exists to deliver.
    assert "check_dispatch" in text
    assert "@workspace" in text


def test_install_hermes_skill_installed_even_when_config_already_registered(
    fake_hermes_config: Path,
) -> None:
    # First run registers config + skill; delete the skill and re-run —
    # the "already registered — no change" path must still restore it.
    assert install.install("hermes") == 0
    skill = _skill_path(fake_hermes_config)
    skill.unlink()
    assert install.install("hermes") == 0
    assert skill.exists()


def test_install_hermes_skill_idempotent(
    fake_hermes_config: Path, capsys: pytest.CaptureFixture
) -> None:
    assert install.install("hermes") == 0
    capsys.readouterr()
    assert install.install("hermes") == 0
    out = capsys.readouterr().out
    assert "skill up to date" in out


def test_install_hermes_skill_refreshes_local_edits(
    fake_hermes_config: Path,
) -> None:
    # Explicit `cmcp install hermes` is user intent to sync — local
    # edits to the skill file are overwritten with the shipped content.
    assert install.install("hermes") == 0
    skill = _skill_path(fake_hermes_config)
    skill.write_text("# user hacked this\n")
    assert install.install("hermes") == 0
    assert "name: central-mcp" in skill.read_text()


def test_install_hermes_dry_run_does_not_write_skill(
    fake_hermes_config: Path,
) -> None:
    rc = install.install("hermes", dry_run=True)
    assert rc == 0
    assert not _skill_path(fake_hermes_config).exists()


# ─── gjc (gajae-code) ─────────────────────────────────────────────────


@pytest.fixture
def fake_gjc_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed `$HOME/.gjc/agent/mcp.json` with a pre-existing server so the
    test can verify merge behavior. Returns the mcp.json path."""
    home = tmp_path / "home"
    (home / ".gjc" / "agent").mkdir(parents=True)
    cfg = home / ".gjc" / "agent" / "mcp.json"
    cfg.write_text(
        '{"mcpServers": {"other": {"type": "stdio", '
        '"command": "other-binary", "args": ["serve"]}}}\n'
    )
    monkeypatch.setenv("HOME", str(home))
    return cfg


def test_install_gjc_adds_entry(fake_gjc_home: Path) -> None:
    import json as _json

    assert install.install("gjc") == 0
    data = _json.loads(fake_gjc_home.read_text())
    entry = data["mcpServers"]["central"]
    assert entry == {"type": "stdio", "command": "central-mcp", "args": ["serve"]}
    # Preserves the pre-existing server entry.
    assert "other" in data["mcpServers"]


def test_install_gjc_is_idempotent(fake_gjc_home: Path) -> None:
    assert install.install("gjc") == 0
    text_before = fake_gjc_home.read_text()
    assert install.install("gjc") == 0
    assert fake_gjc_home.read_text() == text_before


def test_install_gjc_creates_missing_mcp_json(fake_gjc_home: Path) -> None:
    import json as _json

    fake_gjc_home.unlink()  # ~/.gjc exists, mcp.json doesn't (fresh gjc)
    assert install.install("gjc") == 0
    data = _json.loads(fake_gjc_home.read_text())
    assert "central" in data["mcpServers"]


def test_install_gjc_refuses_if_no_gjc_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert install.install("gjc") == 1


def test_install_gjc_dry_run_does_not_write(fake_gjc_home: Path) -> None:
    text_before = fake_gjc_home.read_text()
    assert install.install("gjc", dry_run=True) == 0
    assert fake_gjc_home.read_text() == text_before

