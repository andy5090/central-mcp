"""Token usage aggregation store at `~/.central-mcp/tokens.db` (SQLite).

Single table `usage`, one row per observed turn/dispatch that reported
token counts. Additive via `SUM(...) GROUP BY project` rather than
pre-aggregated, so we never have to back-fill summaries when a late
orchestrator session turn drifts into view.

Identity:
  - `source='dispatch'`    rows are keyed by `dispatch_id`
  - `source='orchestrator'` rows are keyed by `(session_id, request_id)`
A UNIQUE(source, session_id, request_id) constraint makes re-sync of
orchestrator session files idempotent (`INSERT OR IGNORE`).

All public functions are best-effort — they swallow exceptions so a
corrupt DB file or a schema mismatch never breaks dispatch. Callers
treat missing rows as "no token data" rather than surfacing errors.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from central_mcp import paths


def db_path() -> Path:
    return paths.central_mcp_home() / "tokens.db"


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS usage (
    ts             TEXT    NOT NULL,
    project        TEXT,
    agent          TEXT    NOT NULL,
    source         TEXT    NOT NULL CHECK(source IN ('dispatch', 'orchestrator')),
    dispatch_id    TEXT,
    session_id     TEXT,
    request_id     TEXT,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cache_read     INTEGER,
    cache_write    INTEGER,
    total_tokens   INTEGER,
    UNIQUE(source, session_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_usage_ts      ON usage(ts);
CREATE INDEX IF NOT EXISTS idx_usage_project ON usage(project, ts);
CREATE INDEX IF NOT EXISTS idx_usage_source  ON usage(source);
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


def record(
    *,
    ts: str,
    project: str | None,
    agent: str,
    source: str,
    dispatch_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read: int | None = None,
    cache_write: int | None = None,
    total_tokens: int | None = None,
) -> None:
    """Best-effort insert of one usage row. Never raises."""
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO usage
                (ts, project, agent, source, dispatch_id, session_id, request_id,
                 input_tokens, output_tokens, cache_read, cache_write, total_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, project, agent, source, dispatch_id, session_id, request_id,
                 input_tokens, output_tokens, cache_read, cache_write, total_tokens),
            )
    except Exception:
        pass


# ── windowing ────────────────────────────────────────────────────────────────

def _resolve_tz(tz_str: str | None) -> Any:
    """Resolve a user-facing timezone name into a tzinfo; fall back to UTC."""
    if not tz_str:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_str)
    except Exception:
        return timezone.utc


def _window_utc(tz_str: str | None, days: int) -> tuple[str, str]:
    """Return [start_utc_iso, end_utc_iso) bounding the last `days` days.

    `days=1` → today in the user's tz.
    `days=7` → last 7 days including today (6 days ago 00:00 through
    tomorrow 00:00, both in user's tz, expressed in UTC).

    Bounds are ISO 8601 strings with `milliseconds` precision so they
    collate correctly against the `ts` column (which is written by
    `log_timeline` / `record` using the same timespec).
    """
    tz = _resolve_tz(tz_str)
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = today_start + timedelta(days=1)
    start_local = today_start - timedelta(days=max(0, days - 1))
    start_utc = start_local.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    end_utc = end_local.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return start_utc, end_utc


def _aggregate(start: str, end: str) -> dict[str, dict[str, int]]:
    """Return {project: {dispatch, orchestrator, total}} summed over [start, end)."""
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(project, '') AS project,
                       source,
                       SUM(COALESCE(total_tokens, 0)) AS total
                FROM usage
                WHERE ts >= ? AND ts < ?
                GROUP BY project, source
                """,
                (start, end),
            ).fetchall()
    except Exception:
        return {}
    result: dict[str, dict[str, int]] = {}
    for r in rows:
        proj = r["project"]
        entry = result.setdefault(proj, {"dispatch": 0, "orchestrator": 0})
        entry[r["source"]] = int(r["total"] or 0)
    for v in result.values():
        v["total"] = v["dispatch"] + v["orchestrator"]
    return result


def today_by_project(tz_str: str | None) -> dict[str, dict[str, int]]:
    """Token sums per project for the user's "today" (local tz)."""
    start, end = _window_utc(tz_str, days=1)
    return _aggregate(start, end)


def week_by_project(tz_str: str | None) -> dict[str, dict[str, int]]:
    """Token sums per project for the last 7 local-tz days (inclusive)."""
    start, end = _window_utc(tz_str, days=7)
    return _aggregate(start, end)


# ── general-purpose aggregation (for token_usage MCP tool) ───────────────────

_PERIOD_DAYS = {"today": 1, "week": 7, "month": 30}


def _resolve_window(period: str, tz_str: str | None) -> tuple[str | None, str | None]:
    """Translate a period label into a (start_utc, end_utc) pair.

    `period="all"` returns (None, None) → no bounds.
    """
    if period == "all":
        return None, None
    days = _PERIOD_DAYS.get(period, 1)
    return _window_utc(tz_str, days=days)


def aggregate(
    period: str = "today",
    tz_str: str | None = None,
    project_filter: set[str] | None = None,
    group_by: str = "project",
) -> dict[str, Any]:
    """Flexible token-usage aggregation.

    period: today | week | month | all
    project_filter: include only these projects (None = all)
    group_by: project | agent | source

    Returns:
      {
        "window": {"start": ISO, "end": ISO},      # (None, None) when period='all'
        "breakdown": {
           "<group_key>": {"dispatch": N, "orchestrator": M, "total": N+M,
                           "input": X, "output": Y}
        },
        "total": {...}    # sum across all groups
      }
    """
    start, end = _resolve_window(period, tz_str)
    if group_by not in ("project", "agent", "source"):
        group_by = "project"

    # Build query dynamically.
    group_col = {"project": "COALESCE(project, '')",
                 "agent": "agent",
                 "source": "source"}[group_by]
    where_parts: list[str] = []
    params: list[Any] = []
    if start is not None:
        where_parts.append("ts >= ?")
        params.append(start)
    if end is not None:
        where_parts.append("ts < ?")
        params.append(end)
    if project_filter is not None:
        placeholders = ",".join("?" * len(project_filter))
        if project_filter:
            where_parts.append(f"COALESCE(project, '') IN ({placeholders})")
            params.extend(sorted(project_filter))
        else:
            # Empty filter = match nothing; short-circuit.
            return {
                "window": {"start": start, "end": end},
                "breakdown": {},
                "total": {"dispatch": 0, "orchestrator": 0, "total": 0,
                          "input": 0, "output": 0},
            }
    where_sql = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""

    sql = f"""
        SELECT {group_col} AS grp,
               source,
               SUM(COALESCE(input_tokens, 0))  AS input_sum,
               SUM(COALESCE(output_tokens, 0)) AS output_sum,
               SUM(COALESCE(total_tokens, 0))  AS total_sum
        FROM usage
        {where_sql}
        GROUP BY grp, source
    """
    try:
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception:
        return {
            "window": {"start": start, "end": end},
            "breakdown": {},
            "total": {"dispatch": 0, "orchestrator": 0, "total": 0,
                      "input": 0, "output": 0},
        }

    breakdown: dict[str, dict[str, int]] = {}
    for r in rows:
        key = r["grp"]
        # Orchestrator-session tokens have NULL project (COALESCEd to '');
        # surface them under an explicit, capitalized key so consumers
        # don't have to guess what the empty string means and can render
        # the row distinctly from real project names.
        if group_by == "project" and key == "":
            key = "ORCHESTRATOR"
        entry = breakdown.setdefault(key, {
            "dispatch": 0, "orchestrator": 0, "total": 0,
            "input": 0, "output": 0,
        })
        entry[r["source"]] = int(r["total_sum"] or 0)
        entry["input"]  += int(r["input_sum"]  or 0)
        entry["output"] += int(r["output_sum"] or 0)
    for v in breakdown.values():
        v["total"] = v["dispatch"] + v["orchestrator"]

    # Pin ORCHESTRATOR to the top of the breakdown — Python dicts
    # preserve insertion order so this is the rendering hint to clients.
    if "ORCHESTRATOR" in breakdown:
        ordered: dict[str, dict[str, int]] = {
            "ORCHESTRATOR": breakdown["ORCHESTRATOR"],
        }
        for k, v in breakdown.items():
            if k != "ORCHESTRATOR":
                ordered[k] = v
        breakdown = ordered

    total: dict[str, int] = {"dispatch": 0, "orchestrator": 0, "total": 0,
                             "input": 0, "output": 0}
    for v in breakdown.values():
        for k in total:
            total[k] += v[k]

    return {
        "window": {"start": start, "end": end},
        "breakdown": breakdown,
        "total": total,
    }
