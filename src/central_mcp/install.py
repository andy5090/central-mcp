"""Register central-mcp with MCP clients.

Each install function is idempotent: rerunning after a successful install
is a no-op (or updates to match current config). Destructive edits are
always preceded by a timestamped backup of the target file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import tomlkit

SERVER_NAME = "central"
LAUNCH_COMMAND = "central-mcp"
LAUNCH_ARGS: list[str] = ["serve"]


def _backup(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak-{stamp}")
    shutil.copy2(path, bak)
    return bak


def _say(msg: str) -> None:
    print(msg)


def install(client: str, *, dry_run: bool = False) -> int:
    if client == "claude":
        return _install_claude(dry_run=dry_run)
    if client == "codex":
        return _install_codex(dry_run=dry_run)
    if client == "gemini":
        return _install_gemini(dry_run=dry_run)
    if client == "opencode":
        return _install_opencode(dry_run=dry_run)
    print(
        f"error: unknown client {client!r}. "
        "Supported: claude, codex, gemini, opencode.",
        file=sys.stderr,
    )
    return 1


def ensure_codex_trust(project_path: str) -> str | None:
    """Add a trusted project entry to ~/.codex/config.toml if missing.

    Returns a status message, or None if nothing was needed/possible.
    Idempotent — re-calling with the same path is a no-op.
    """
    cfg = Path.home() / ".codex" / "config.toml"
    if not cfg.exists():
        return None  # codex not installed — skip silently

    doc = tomlkit.parse(cfg.read_text())
    projects = doc.get("projects")
    if projects is None:
        projects = tomlkit.table(is_super_table=True)
        doc["projects"] = projects

    key = project_path
    if key in projects:
        existing = projects[key]
        if existing.get("trust_level") == "trusted":
            return f"codex: {key} already trusted"
        existing["trust_level"] = "trusted"
    else:
        entry = tomlkit.table()
        entry["trust_level"] = "trusted"
        projects[key] = entry

    bak = _backup(cfg)
    cfg.write_text(tomlkit.dumps(doc))
    return f"codex: trusted {key} (backup: {bak})"


def _install_claude(*, dry_run: bool) -> int:
    # --scope user registers the MCP server under the user profile instead
    # of the local/project scope of the caller's cwd. Without this flag the
    # server would only be visible to sessions started from the exact
    # directory where `central-mcp install claude` ran — so a subsequent
    # `central-mcp run` (which launches Claude Code from ~/.central-mcp/)
    # would not see it and Claude would report "not registered".
    cmd = [
        "claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--",
        LAUNCH_COMMAND, *LAUNCH_ARGS,
    ]
    _say("Would run: " + " ".join(cmd) if dry_run else "Running: " + " ".join(cmd))
    if dry_run:
        return 0
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print("error: `claude` CLI not found in PATH", file=sys.stderr)
        return 1
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def _install_codex(*, dry_run: bool) -> int:
    cfg = Path.home() / ".codex" / "config.toml"
    if not cfg.exists():
        print(f"error: {cfg} does not exist — install codex first", file=sys.stderr)
        return 1

    doc = tomlkit.parse(cfg.read_text())
    servers = doc.setdefault("mcp_servers", tomlkit.table())
    if SERVER_NAME in servers and not dry_run:
        existing = servers[SERVER_NAME]
        if (
            existing.get("command") == LAUNCH_COMMAND
            and list(existing.get("args") or []) == LAUNCH_ARGS
        ):
            _say(f"already registered in {cfg} — no change")
            return 0

    entry = tomlkit.table()
    entry["command"] = LAUNCH_COMMAND
    entry["args"] = LAUNCH_ARGS
    entry["startup_timeout_sec"] = 15.0
    servers[SERVER_NAME] = entry

    if dry_run:
        _say(f"Would write to {cfg}:")
        _say(tomlkit.dumps(doc))
        return 0

    bak = _backup(cfg)
    cfg.write_text(tomlkit.dumps(doc))
    _say(f"updated {cfg}")
    _say(f"backup: {bak}")
    return 0


def _install_opencode(*, dry_run: bool) -> int:
    """Register central-mcp inside opencode's config.json.

    opencode reads MCP servers from ~/.config/opencode/opencode.json under
    the top-level ``mcp`` object. Entry shape:

        {"mcp": {"central": {"type": "local", "command": ["central-mcp", "serve"]}}}
    """
    cfg_dir = Path.home() / ".config" / "opencode"
    cfg = cfg_dir / "opencode.json"

    if cfg.exists():
        try:
            doc = json.loads(cfg.read_text() or "{}")
        except json.JSONDecodeError as exc:
            print(f"error: {cfg} is not valid JSON: {exc}", file=sys.stderr)
            return 1
    else:
        doc = {}
    if not isinstance(doc, dict):
        print(f"error: {cfg} root must be a JSON object", file=sys.stderr)
        return 1

    servers = doc.setdefault("mcp", {})
    if not isinstance(servers, dict):
        print(f"error: {cfg} mcp must be an object", file=sys.stderr)
        return 1

    desired_cmd = [LAUNCH_COMMAND, *LAUNCH_ARGS]
    existing = servers.get(SERVER_NAME)
    if (
        isinstance(existing, dict)
        and existing.get("type") == "local"
        and list(existing.get("command") or []) == desired_cmd
    ):
        _say(f"already registered in {cfg} — no change")
        return 0

    servers[SERVER_NAME] = {"type": "local", "command": desired_cmd}
    new_text = json.dumps(doc, indent=2) + "\n"

    if dry_run:
        _say(f"Would write to {cfg}:")
        _say(new_text)
        return 0

    cfg_dir.mkdir(parents=True, exist_ok=True)
    bak = _backup(cfg) if cfg.exists() else None
    cfg.write_text(new_text)
    _say(f"updated {cfg}")
    if bak:
        _say(f"backup: {bak}")
    return 0


def _install_gemini(*, dry_run: bool) -> int:
    """Register central-mcp inside Gemini CLI's settings.json.

    Gemini CLI reads MCP server configuration from ~/.gemini/settings.json
    under the top-level `mcpServers` object. Entry shape:

        {"mcpServers": {"central": {"command": "central-mcp", "args": ["serve"]}}}

    This installer is idempotent and creates the file (with parent dir)
    if it doesn't exist yet, mirroring Claude/Codex behavior.
    """
    cfg_dir = Path.home() / ".gemini"
    cfg = cfg_dir / "settings.json"

    if cfg.exists():
        try:
            doc = json.loads(cfg.read_text() or "{}")
        except json.JSONDecodeError as exc:
            print(f"error: {cfg} is not valid JSON: {exc}", file=sys.stderr)
            return 1
    else:
        # Create a minimal settings.json rather than failing — the user
        # may have installed Gemini CLI but never opened it interactively.
        doc = {}
    if not isinstance(doc, dict):
        print(f"error: {cfg} root must be a JSON object", file=sys.stderr)
        return 1

    servers = doc.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        print(f"error: {cfg} mcpServers must be an object", file=sys.stderr)
        return 1

    desired = {"command": LAUNCH_COMMAND, "args": list(LAUNCH_ARGS)}
    existing = servers.get(SERVER_NAME)
    if (
        isinstance(existing, dict)
        and existing.get("command") == desired["command"]
        and list(existing.get("args") or []) == desired["args"]
    ):
        _say(f"already registered in {cfg} — no change")
        return 0

    servers[SERVER_NAME] = desired
    new_text = json.dumps(doc, indent=2) + "\n"

    if dry_run:
        _say(f"Would write to {cfg}:")
        _say(new_text)
        return 0

    cfg_dir.mkdir(parents=True, exist_ok=True)
    bak = _backup(cfg) if cfg.exists() else None
    cfg.write_text(new_text)
    _say(f"updated {cfg}")
    if bak:
        _say(f"backup: {bak}")
    return 0


