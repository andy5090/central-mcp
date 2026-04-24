"""Shared dispatch state at `~/.central-mcp/dispatches.db` (SQLite).

Each MCP stdio connection historically spawned its own central-mcp
process with a private `_dispatches` dict, so a sub-agent spawned by
the orchestrator (e.g. a Codex polling agent) would connect to a
DIFFERENT central-mcp instance and report "no dispatch with id <X>"
even when the main orchestrator's instance had just started it.

This module is the lightweight fix: all dispatch state lands in a
shared SQLite table, and `check_dispatch` / `list_dispatches` fall
through to this store when the record isn't in the caller's
in-memory dict. In-memory state still wins for the originating
process (free, no I/O); DB is the authoritative source across
processes.

Schema is deliberately flat — one row per dispatch, overwritten on
each state transition (started → running → complete/error/cancelled).
Writes are best-effort and never raise.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from central_mcp import paths


def db_path() -> Path:
    return paths.central_mcp_home() / "dispatches.db"


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS dispatches (
    id             TEXT    PRIMARY KEY,
    project        TEXT    NOT NULL,
    agent          TEXT,
    status         TEXT    NOT NULL,     -- running | complete | error | cancelled | timeout
    started_at     TEXT    NOT NULL,     -- ISO 8601 UTC
    finished_at    TEXT,
    duration_sec   REAL,
    exit_code      INTEGER,
    ok             INTEGER,              -- 0 / 1 / NULL (while running)
    fallback_used  INTEGER DEFAULT 0,
    prompt_preview TEXT,
    command        TEXT,
    output         TEXT,
    stderr         TEXT,
    error          TEXT,
    tokens_json    TEXT,                 -- JSON-encoded tokens dict
    chain_json     TEXT,                 -- JSON-encoded agent-chain list
    updated_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dispatches_status
    ON dispatches(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_dispatches_project
    ON dispatches(project, started_at);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _to_json(val: Any) -> str | None:
    if val is None:
        return None
    try:
        return json.dumps(val, ensure_ascii=False)
    except Exception:
        return None


# ── writes (best-effort, never raise) ────────────────────────────────────────

def upsert_started(entry: dict[str, Any]) -> None:
    """Record a new dispatch at dispatch() time.

    `entry` mirrors the in-memory _dispatches record. Only the subset
    of keys we care about is lifted; extras are ignored.
    """
    try:
        started_at = datetime.fromtimestamp(
            entry.get("started") or time.time(), tz=timezone.utc
        ).isoformat(timespec="milliseconds")
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO dispatches
                (id, project, agent, status, started_at, prompt_preview,
                 command, chain_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["id"],
                    entry["project"],
                    entry.get("agent"),
                    entry.get("status", "running"),
                    started_at,
                    (entry.get("prompt") or "")[:500],
                    entry.get("command"),
                    _to_json(entry.get("chain")),
                    _now_iso(),
                ),
            )
    except Exception:
        pass


def upsert_finished(
    dispatch_id: str,
    status: str,
    result: dict[str, Any] | None,
) -> None:
    """Update a dispatch's terminal state (complete/error/cancelled/timeout)."""
    try:
        result = result or {}
        finished_at = _now_iso()
        with _connect() as conn:
            conn.execute(
                """
                UPDATE dispatches SET
                    status        = ?,
                    finished_at   = ?,
                    duration_sec  = ?,
                    exit_code     = ?,
                    ok            = ?,
                    fallback_used = ?,
                    output        = ?,
                    stderr        = ?,
                    error         = ?,
                    tokens_json   = ?,
                    agent         = COALESCE(?, agent),
                    updated_at    = ?
                WHERE id = ?
                """,
                (
                    status,
                    finished_at,
                    result.get("duration_sec"),
                    result.get("exit_code"),
                    1 if result.get("ok") else 0,
                    1 if result.get("fallback_used") else 0,
                    result.get("output"),
                    result.get("stderr"),
                    result.get("error"),
                    _to_json(result.get("tokens")),
                    result.get("agent_used"),
                    _now_iso(),
                    dispatch_id,
                ),
            )
    except Exception:
        pass


def mark_cancel_requested(dispatch_id: str) -> None:
    """Signal to other processes that a cancel has been requested.

    The actual process kill can only be performed by the originating
    central-mcp instance (it holds the subprocess handle). Other
    instances learn about the cancellation the next time the
    originating instance writes a terminal update.
    """
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE dispatches SET updated_at = ? WHERE id = ?",
                (_now_iso(), dispatch_id),
            )
    except Exception:
        pass


# ── reads ────────────────────────────────────────────────────────────────────

def _row_to_entry(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Translate a DB row into the same shape as the in-memory _dispatches
    entry so server.py consumers don't care where it came from."""
    if row is None:
        return None
    try:
        tokens = json.loads(row["tokens_json"]) if row["tokens_json"] else None
    except Exception:
        tokens = None
    try:
        chain = json.loads(row["chain_json"]) if row["chain_json"] else []
    except Exception:
        chain = []
    # Translate started_at (ISO string) back into a float for `time.time()`
    # consumers that want elapsed_sec; keep ISO form too.
    try:
        started_epoch = datetime.fromisoformat(
            row["started_at"].replace("Z", "+00:00")
        ).timestamp()
    except Exception:
        started_epoch = time.time()

    result = {
        "ok": bool(row["ok"]) if row["ok"] is not None else None,
        "exit_code": row["exit_code"],
        "output": row["output"] or "",
        "stderr": row["stderr"] or "",
        "error": row["error"],
        "duration_sec": row["duration_sec"],
        "fallback_used": bool(row["fallback_used"]),
        "tokens": tokens,
        "agent_used": row["agent"],
    }
    # For still-running entries the result is None by convention.
    if row["status"] == "running":
        result = None

    return {
        "id":        row["id"],
        "project":   row["project"],
        "agent":     row["agent"],
        "chain":     chain,
        "prompt":    row["prompt_preview"] or "",
        "command":   row["command"],
        "status":    row["status"],
        "started":   started_epoch,
        "process":   None,      # not shared across processes
        "result":    result,
        "attempts":  [],        # full attempt history not mirrored — keep
                                # in memory for performance and detailed
                                # inspection locally.
        "_from_db":  True,
    }


def get(dispatch_id: str) -> dict[str, Any] | None:
    """Return the shared-state entry for `dispatch_id`, or None if missing."""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM dispatches WHERE id = ?", (dispatch_id,)
            ).fetchone()
    except Exception:
        return None
    return _row_to_entry(row)


def list_all(limit: int = 200) -> list[dict[str, Any]]:
    """Return recent dispatches, newest first."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dispatches ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        entry = _row_to_entry(r)
        if entry is not None:
            out.append(entry)
    return out


def list_active() -> list[dict[str, Any]]:
    """Return dispatches currently in the `running` status."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT * FROM dispatches WHERE status = 'running' "
                "ORDER BY started_at ASC"
            ).fetchall()
    except Exception:
        return []
    return [e for r in rows if (e := _row_to_entry(r)) is not None]
