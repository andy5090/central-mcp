"""Dispatch ↔ MCP Tasks-extension translation layer.

Phase 1 of the roadmap's "Ecosystem alignment" track (docs/ROADMAP.md).
The MCP 2026-07-28 spec promotes long-running work to an official Tasks
extension whose lifecycle — `tools/call` returns a task handle, the
client polls `tasks/get` / `tasks/cancel` — is the same shape as our
`dispatch` → `check_dispatch` → `cancel_dispatch` tools. This module
holds the pure translation between the two vocabularies so the Phase-2
wire-up (advertising the extension on an SDK that speaks it) stays a
thin layer.

Deliberately dependency-free: input is the dispatch-entry dict shape
shared by `server.py`'s in-memory `_dispatches` records and
`dispatches_db._row_to_entry`, output is a plain dict tracking the RC's
task-object shape. No `mcp` / `fastmcp` imports here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Dispatch status vocabulary (dispatches.db `status` column) → Tasks
# lifecycle vocabulary. `input_required` has no dispatch equivalent yet;
# PTY-mode dispatches waiting on a human answer are the future candidate.
DISPATCH_TO_TASK_STATUS: dict[str, str] = {
    "running":   "working",
    "complete":  "completed",
    "error":     "failed",
    "timeout":   "failed",
    "cancelled": "cancelled",
}

TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})

# Matches the "poll check_dispatch every 3 s" guidance shipped in
# data/CLAUDE.md — one number, two surfaces.
POLL_INTERVAL_MS = 3000

# Reverse-DNS namespace for central-mcp fields inside task `_meta`,
# per the RC's extension/metadata naming convention.
META_KEY = "io.github.andy5090.central-mcp/dispatch"


def task_status(dispatch_status: str | None) -> str:
    """Map a dispatch status onto the Tasks vocabulary.

    Unknown / future statuses map to "working": misreporting an
    in-flight state as terminal would make pollers abandon a live
    dispatch, which is the worse failure.
    """
    return DISPATCH_TO_TASK_STATUS.get(dispatch_status or "", "working")


def is_terminal(status: str) -> bool:
    """True if `status` (Tasks vocabulary) is a terminal state."""
    return status in TERMINAL_TASK_STATUSES


def _iso_utc(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
    except Exception:
        return None


def _status_message(entry: dict[str, Any]) -> str | None:
    """Human-readable one-liner for failed/cancelled tasks."""
    status = entry.get("status")
    if status == "timeout":
        return "dispatch timed out"
    if status == "cancelled":
        return "dispatch cancelled"
    result = entry.get("result") or {}
    if status == "error":
        return result.get("error") or "dispatch failed"
    return None


def to_task(entry: dict[str, Any]) -> dict[str, Any]:
    """Render a dispatch entry as a Tasks-extension task object.

    `entry` is the shape returned by `dispatches_db.get()` /
    `_row_to_entry` (and mirrored by server.py's in-memory records):
    keys `id`, `project`, `agent`, `status`, `started`, `result`.
    """
    status = task_status(entry.get("status"))
    task: dict[str, Any] = {
        "taskId": entry["id"],
        "status": status,
        "createdAt": _iso_utc(entry.get("started")),
        "pollInterval": POLL_INTERVAL_MS,
        "_meta": {
            META_KEY: {
                "project": entry.get("project"),
                "agent": entry.get("agent"),
            }
        },
    }
    message = _status_message(entry)
    if message is not None:
        task["statusMessage"] = message
    return task
