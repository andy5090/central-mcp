"""Live PTY session registry — `~/.central-mcp/pty-sessions/<project>.json`.

When a project's agent CLI is running inside a TUI's `PtyTerminal`, the
widget writes a small JSON file here on spawn and removes it on unmount.
The MCP `dispatch()` tool consults this registry and rejects calls into
projects with an active PTY: a human is supervising that pane and an
incoming background prompt would either get swallowed by an in-progress
permission dialog or splice itself into whatever the user is typing.

Stale-PID sweep on read: if the registered PID is gone (TUI crash, kill
-9, machine reboot), the entry is removed and the project becomes
dispatchable again on the same call.

Writes happen only from the TUI process; readers (`server.py::dispatch`,
status tools) only consult.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from central_mcp import paths


def _registry_dir() -> Path:
    return paths.central_mcp_home() / "pty-sessions"


def _entry_path(project: str) -> Path:
    return _registry_dir() / f"{project}.json"


def _alive(pid: int) -> bool:
    """Return True iff `pid` names a live process on this host."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists, owned by someone else — still counts as alive.
        return True
    except OSError:
        return False
    return True


def _read_entry(path: Path) -> dict[str, Any] | None:
    """Read one entry; sweep + return None if the entry is stale or unparseable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        # Corrupt → remove
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    pid = data.get("pid")
    if not isinstance(pid, int) or not _alive(pid):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    return data


def register(project: str, pid: int, agent: str) -> None:
    """Mark `project` as PTY-active. Best-effort, never raises."""
    try:
        d = _registry_dir()
        d.mkdir(parents=True, exist_ok=True)
        entry = {
            "project": project,
            "pid": pid,
            "agent": agent,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _entry_path(project).write_text(
            json.dumps(entry, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def unregister(project: str) -> None:
    """Remove the PTY registration for `project`. Safe if missing."""
    try:
        _entry_path(project).unlink(missing_ok=True)
    except Exception:
        pass


def is_active(project: str) -> bool:
    """True iff `project` has a live PTY session registered.

    Reads sweep stale entries automatically, so a crash-left-behind file
    doesn't permanently block dispatches.
    """
    return _read_entry(_entry_path(project)) is not None


def get(project: str) -> dict[str, Any] | None:
    """Return the live registration entry, or None if absent / stale."""
    return _read_entry(_entry_path(project))


def list_active() -> list[dict[str, Any]]:
    """Return every live PTY registration. Stale entries are swept."""
    d = _registry_dir()
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return []
    for p in files:
        entry = _read_entry(p)
        if entry is not None:
            out.append(entry)
    return out
