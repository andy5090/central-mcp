"""Observation-session metadata stamp.

Records which central-mcp version built a given tmux/zellij session
and which multiplexer it targets. 0.6.8 made session rebuilds
automatic on every `cmcp tmux` / `cmcp zellij`, so this file's
original stale-attach guard is no longer wired up — the module
survives as a lightweight breadcrumb for debugging / external tools
that want to peek at the running session's provenance.

File format (tomlkit, matches config.toml's style):

    version = "0.6.8"
    multiplexer = "zellij"   # or "tmux"
    created_at = "2026-04-21T17:42:00Z"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

import tomlkit

from central_mcp import paths


@dataclass(frozen=True)
class SessionStamp:
    version: str
    multiplexer: str
    created_at: str


def current_version() -> str:
    """Current installed central-mcp version, or '0.0.0-dev' in a
    source checkout where the package metadata isn't available."""
    try:
        return _pkg_version("central-mcp")
    except PackageNotFoundError:
        return "0.0.0-dev"


def write(multiplexer: str, *, version: str | None = None) -> Path:
    """Stamp the current session with the running central-mcp version."""
    home = paths.central_mcp_home()
    home.mkdir(parents=True, exist_ok=True)
    doc = tomlkit.document()
    doc["version"] = version or current_version()
    doc["multiplexer"] = multiplexer
    doc["created_at"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    target = paths.session_info_file()
    target.write_text(tomlkit.dumps(doc))
    return target


def read() -> SessionStamp | None:
    """Return the existing stamp, or None if the file is missing or
    malformed (treat both as "no stamp")."""
    target = paths.session_info_file()
    if not target.exists():
        return None
    try:
        raw = tomlkit.parse(target.read_text())
    except Exception:
        return None
    version = raw.get("version")
    multiplexer = raw.get("multiplexer")
    created_at = raw.get("created_at")
    if not isinstance(version, str) or not isinstance(multiplexer, str):
        return None
    return SessionStamp(
        version=version,
        multiplexer=multiplexer,
        created_at=created_at if isinstance(created_at, str) else "",
    )


def clear() -> None:
    """Delete the stamp file if present — called by `cmcp down` so a
    later `cmcp up` always writes a fresh one."""
    target = paths.session_info_file()
    try:
        target.unlink()
    except FileNotFoundError:
        pass


