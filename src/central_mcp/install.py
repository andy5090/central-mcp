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
    if client == "cursor":
        return _install_cursor(dry_run=dry_run)
    print(f"error: unknown client {client!r}", file=sys.stderr)
    return 1


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


def _install_cursor(*, dry_run: bool) -> int:
    cfg = Path.home() / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text())
        except json.JSONDecodeError:
            print(f"error: {cfg} is not valid JSON", file=sys.stderr)
            return 1

    servers = data.setdefault("mcpServers", {})
    entry = {"command": LAUNCH_COMMAND, "args": LAUNCH_ARGS}
    if servers.get(SERVER_NAME) == entry and not dry_run:
        _say(f"already registered in {cfg} — no change")
        return 0
    servers[SERVER_NAME] = entry

    if dry_run:
        _say(f"Would write to {cfg}:")
        _say(json.dumps(data, indent=2))
        return 0

    if cfg.exists():
        bak = _backup(cfg)
        _say(f"backup: {bak}")
    cfg.write_text(json.dumps(data, indent=2) + "\n")
    _say(f"updated {cfg}")
    return 0
