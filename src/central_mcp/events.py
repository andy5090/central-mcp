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
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from central_mcp import paths

try:
    import fcntl  # POSIX (macOS / Linux / WSL)
except ImportError:  # Windows native — fall through to threading.Lock only
    fcntl = None  # type: ignore[assignment]

# Serializes `log_timeline` within this Python process. Guards ts-generation
# against race conditions between the MCP handler thread and `_run_bg` daemon
# threads that both append to ~/.central-mcp/timeline.jsonl.
_timeline_lock = threading.Lock()


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


def token_total(tokens: dict[str, Any] | None) -> int:
    """Coalesce an agent's token dict into a single integer total.

    Prefers the explicit `total` field; falls back to `input + output`.
    Returns 0 for None / empty / unparseable input.
    """
    if not tokens or not isinstance(tokens, dict):
        return 0
    total = tokens.get("total")
    if total:
        try:
            return int(total)
        except (TypeError, ValueError):
            pass
    try:
        return int(tokens.get("input") or 0) + int(tokens.get("output") or 0)
    except (TypeError, ValueError):
        return 0


def log_timeline(dispatch_id: str, project: str, event: str, **data: Any) -> None:
    """Append one milestone to the global timeline.

    Compact by design — no output chunks, just the minimum to tell
    the orchestrator "this dispatch started/finished in project X at
    time T with result Y". Best-effort, never raises.

    Locking: ts-generation and append happen under `_timeline_lock`
    (in-process) and `fcntl.flock` (cross-process on POSIX). This keeps
    the file's line order aligned with ts order so monitor's reverse-
    scan early-break remains safe under concurrent writers.
    """
    try:
        path = timeline_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _timeline_lock:
            with path.open("a") as f:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    record = {
                        "ts": datetime.now(timezone.utc)
                              .isoformat(timespec="milliseconds"),
                        "project": project,
                        "id": dispatch_id,
                        "event": event,
                        **data,
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    f.flush()   # commit to kernel before releasing flock
                finally:
                    if fcntl is not None:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
