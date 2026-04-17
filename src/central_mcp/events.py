"""Per-project dispatch event log — append-only JSONL.

Every dispatch writes structured events to
`~/.central-mcp/logs/<project>/dispatch.jsonl` as it runs. The tmux
observation pane `tail -f`s this file via `central-mcp watch <project>`
to show dispatch activity live. Phase 4+ (ROADMAP.md) will expose the
same file as an MCP resource for external subscribers, so the schema
here is the single source of truth.

Event kinds:
  start     once per dispatch — prompt, agent chain, cwd
  output    one per stdout/stderr chunk (line-oriented, best-effort)
  complete  once per dispatch — exit_code, duration, ok
  error     once per dispatch if an exception escapes

Each record is a one-line JSON object:
  {"ts": "...", "id": "abc123", "event": "start", ...}

Writes are best-effort: a full disk or permission error must never
break dispatch, so every call here swallows its own exceptions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from central_mcp import paths


def log_dir(project: str) -> Path:
    return paths.central_mcp_home() / "logs" / project


def log_path(project: str) -> Path:
    return log_dir(project) / "dispatch.jsonl"


def timeline_path() -> Path:
    """Global cross-project milestone log.

    One line per dispatch lifecycle milestone (dispatched, complete,
    error, cancelled) for every project, chronologically interleaved.
    Backs `orchestration_history` and portfolio-level summaries so
    the orchestrator can answer "how is everything going?" without
    stitching per-project files together.
    """
    return paths.central_mcp_home() / "timeline.jsonl"


def log_event(project: str, dispatch_id: str, event: str, **data: Any) -> None:
    """Append one dispatch event to the project's jsonl log.

    Never raises — logging is best-effort and must not interrupt
    dispatch. Callers do not need to wrap this in try/except.
    """
    try:
        d = log_dir(project)
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "id": dispatch_id,
            "event": event,
            **data,
        }
        with (d / "dispatch.jsonl").open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def log_timeline(dispatch_id: str, project: str, event: str, **data: Any) -> None:
    """Append one milestone to the global timeline.

    Compact by design — no output chunks, just the minimum to tell
    the orchestrator "this dispatch started/finished in project X at
    time T with result Y". Best-effort, never raises.
    """
    try:
        path = timeline_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "project": project,
            "id": dispatch_id,
            "event": event,
            **data,
        }
        with path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
