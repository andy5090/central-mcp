"""Backfill orchestrator-side token usage into `tokens.db`.

Each coding-agent CLI logs its own conversation to disk — Claude Code
to `~/.claude/projects/<slug>/<session_id>.jsonl`, Codex to
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. Those files carry
per-turn token usage that's invisible to central-mcp otherwise (the
orchestrator's LLM calls never flow through an MCP tool).

`sync_orchestrator(agent)` is called from `dispatch()` — it reads the
most recently modified session file for the active orchestrator,
parses per-turn tokens, and inserts them into `tokens.db` under
source='orchestrator'. The UNIQUE(source, session_id, request_id)
constraint (via `INSERT OR IGNORE`) makes the scan idempotent, so we
can replay the whole file on every dispatch without double-counting.

Gemini has no on-disk session store and is a no-op here; opencode's
SQLite-backed sessions will be added in a follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from central_mcp import tokens_db
from central_mcp.registry import load_registry


# ── cwd → project mapping ────────────────────────────────────────────────────

def _project_for_cwd(cwd: str) -> str | None:
    """Match a filesystem cwd to a registered project name, or None."""
    if not cwd:
        return None
    try:
        target = str(Path(cwd).resolve())
    except Exception:
        return None
    for p in load_registry():
        try:
            if str(Path(p.path).resolve()) == target:
                return p.name
        except Exception:
            continue
    return None


# ── per-agent session readers ────────────────────────────────────────────────

def _iter_claude_turns(path: Path) -> Iterator[dict[str, Any]]:
    """Yield one dict per token-bearing assistant event in a Claude Code
    session jsonl. Fields: ts, session_id, request_id, cwd, tokens dict."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                line = ln.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("type") != "assistant":
                    continue
                msg = r.get("message") or {}
                usage = msg.get("usage") or {}
                inp = usage.get("input_tokens")
                out = usage.get("output_tokens")
                if inp is None and out is None:
                    continue
                yield {
                    "ts":         r.get("timestamp") or "",
                    "session_id": r.get("sessionId") or path.stem,
                    "request_id": r.get("requestId") or r.get("uuid") or "",
                    "cwd":        r.get("cwd") or "",
                    "input":      int(inp or 0),
                    "output":     int(out or 0),
                    "total":      int(inp or 0) + int(out or 0),
                    "cache_read":  int(usage.get("cache_read_input_tokens") or 0),
                    "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
                }
    except Exception:
        return


def _iter_codex_turns(path: Path) -> Iterator[dict[str, Any]]:
    """Yield one dict per `event_msg/token_count` record in a Codex
    rollout-*.jsonl. Session_id + cwd are read from the leading
    `session_meta` line."""
    session_id: str | None = None
    cwd: str = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline().strip()
            if first:
                try:
                    meta = json.loads(first)
                    payload = meta.get("payload") or {}
                    session_id = payload.get("id")
                    cwd = payload.get("cwd") or ""
                except Exception:
                    pass
            turn_idx = 0
            for ln in fh:
                line = ln.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("type") != "event_msg":
                    continue
                payload = r.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                info = payload.get("info") or {}
                usage = info.get("last_token_usage")
                if not usage:
                    continue
                turn_idx += 1
                yield {
                    "ts":         r.get("timestamp") or "",
                    "session_id": session_id or path.stem,
                    "request_id": f"turn-{turn_idx}",
                    "cwd":        cwd,
                    "input":      int(usage.get("input_tokens") or 0),
                    "output":     int(usage.get("output_tokens") or 0),
                    "total":      int(usage.get("total_tokens") or 0),
                    "cache_read":  int(usage.get("cached_input_tokens") or 0),
                    "cache_write": 0,
                }
    except Exception:
        return


_READERS: dict[str, Any] = {
    "claude": _iter_claude_turns,
    "codex":  _iter_codex_turns,
    # gemini: no session store → skip
    # opencode: SQLite → follow-up
}


# ── session-file discovery ───────────────────────────────────────────────────

def _recent_session_path(agent: str) -> Path | None:
    """Most recently modified session file for the orchestrator agent."""
    home = Path.home()
    if agent == "claude":
        base = home / ".claude" / "projects"
    elif agent == "codex":
        base = home / ".codex" / "sessions"
    else:
        return None
    if not base.is_dir():
        return None
    best: tuple[float, Path] | None = None
    try:
        for p in base.rglob("*.jsonl"):
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if best is None or mt > best[0]:
                best = (mt, p)
    except Exception:
        return None
    return best[1] if best else None


# ── public entry ─────────────────────────────────────────────────────────────

def sync_orchestrator(agent: str) -> int:
    """Parse the active session for `agent` and INSERT OR IGNORE each
    token-bearing turn into tokens.db. Returns the number of rows
    attempted (not necessarily inserted — dedup is handled by SQLite).

    Never raises. Idempotent — safe to call on every dispatch.
    """
    reader = _READERS.get(agent)
    if reader is None:
        return 0
    path = _recent_session_path(agent)
    if path is None:
        return 0
    count = 0
    for turn in reader(path):
        project = _project_for_cwd(turn["cwd"])
        tokens_db.record(
            ts=turn["ts"],
            project=project,
            agent=agent,
            source="orchestrator",
            session_id=turn["session_id"],
            request_id=turn["request_id"] or None,
            input_tokens=turn["input"],
            output_tokens=turn["output"],
            total_tokens=turn["total"],
            cache_read=turn.get("cache_read"),
            cache_write=turn.get("cache_write"),
        )
        count += 1
    return count
