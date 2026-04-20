"""Observation-session version stamp.

Writes the version of central-mcp that built a given tmux/zellij
session so subsequent attaches can detect when the binary has been
upgraded out from under the running panes. Stale sessions carry
orchestrator processes and `central-mcp watch` children from the old
binary — they keep running but miss anything the new version adds
(new events, new argv flags, updated instruction files). Warning the
user at attach time lets them `cmcp down` and recreate cleanly
before more work happens on top of the stale state.

File format (tomlkit, matches config.toml's style):

    version = "0.6.0"
    multiplexer = "zellij"   # or "tmux"
    created_at = "2026-04-20T17:42:00Z"

Missing file = "no stamp yet" (legacy / never tracked) — callers
treat this as "fresh enough, just stamp it".
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


def staleness_warning(stamp: SessionStamp | None, now: str | None = None) -> str | None:
    """Return a human-readable warning when the running session's
    stamp doesn't match the installed version, else None.

    A missing stamp is NOT stale — legacy sessions from before this
    mechanism existed are allowed to attach without complaint. Only
    an actual version mismatch triggers the warning.
    """
    if stamp is None:
        return None
    running = now or current_version()
    if stamp.version == running:
        return None
    return (
        f"observation session was created by central-mcp {stamp.version} "
        f"but you're now running {running}. Existing panes still hold the "
        f"old version's orchestrator + watch processes, so new features "
        f"(e.g. added event types, updated argv flags) may not appear. "
        f"Run `cmcp down && cmcp {stamp.multiplexer}` to rebuild cleanly, "
        f"or re-run with --force-recreate to do it in one step."
    )
