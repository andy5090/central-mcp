"""Aggregate Hermes Agent usage from ``~/.hermes/state.db``.

Unlike claude / codex / gemini, hermes has no upstream quota endpoint —
it's provider-neutral, so "you've used 80% of your plan" doesn't apply.
What it does have is a rich local SQLite session ledger (input /
output / cache_read / cache_write / reasoning tokens, plus
``actual_cost_usd`` per session) maintained by `hermes` itself.

This fetcher rolls those rows up into hour / day / week windows so the
quota HUD has something concrete to display alongside the
subscription-cap providers. Reads use ``mode=ro`` so a concurrent
``hermes`` process holding write locks never blocks our snapshot.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    """Resolved at call time so test monkeypatches of $HOME take effect."""
    return Path.home() / ".hermes" / "state.db"


_WINDOWS_SEC: dict[str, int] = {
    "hour": 3600,
    "day":  86400,
    "week": 86400 * 7,
}


def _zero_window() -> dict[str, Any]:
    return {
        "input_tokens":       0,
        "output_tokens":      0,
        "cache_read_tokens":  0,
        "cache_write_tokens": 0,
        "reasoning_tokens":   0,
        "total_tokens":       0,
        "cost_usd":           0.0,
        "sessions":           0,
    }


def fetch() -> dict[str, Any]:
    """Return rolled-up token + cost usage for the rolling windows.

    Possible shapes:
      ``{"mode": "not_installed"}``                 — no state.db at all
      ``{"mode": "error", "error": "..."}``         — db unreadable
      ``{"mode": "local_ledger", "hour": {...},
        "day": {...}, "week": {...}}``              — happy path
    """
    path = _db_path()
    if not path.exists():
        return {"mode": "not_installed"}

    out: dict[str, Any] = {"mode": "local_ledger"}
    now = time.time()
    try:
        # Read-only URI so a concurrent `hermes` writer doesn't block us.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
        try:
            for label, secs in _WINDOWS_SEC.items():
                cutoff = now - secs
                row = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(input_tokens), 0),
                        COALESCE(SUM(output_tokens), 0),
                        COALESCE(SUM(cache_read_tokens), 0),
                        COALESCE(SUM(cache_write_tokens), 0),
                        COALESCE(SUM(reasoning_tokens), 0),
                        COALESCE(SUM(actual_cost_usd), 0.0),
                        COUNT(*)
                    FROM sessions
                    WHERE started_at >= ?
                    """,
                    (cutoff,),
                ).fetchone()
                if row is None:
                    out[label] = _zero_window()
                    continue
                inp, outp, cr, cw, rs, cost, count = row
                out[label] = {
                    "input_tokens":       int(inp or 0),
                    "output_tokens":      int(outp or 0),
                    "cache_read_tokens":  int(cr or 0),
                    "cache_write_tokens": int(cw or 0),
                    "reasoning_tokens":   int(rs or 0),
                    "total_tokens":       int((inp or 0) + (outp or 0)),
                    "cost_usd":           round(float(cost or 0.0), 4),
                    "sessions":           int(count or 0),
                }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"mode": "error", "error": str(exc)}
    return out
