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

    Automatically rotated into `archive/` once it exceeds
    `_ROTATE_BYTES` or `_ROTATE_LINES`; readers that care about the
    full history call `list_archives()` / `read_archive_summary()`.
    """
    return paths.central_mcp_home() / "timeline.jsonl"


def archive_dir() -> Path:
    """Where rotated `timeline-<ts>.jsonl` + `*-summary.json` pairs live."""
    return paths.central_mcp_home() / "archive"


# Rotation thresholds. Deliberately generous — a working install at ~500
# dispatches/day needs years to hit 5 MB — so the default behaviour is
# "dormant, correct when it matters". Monkeypatch in tests to exercise
# the rotate path.
_ROTATE_BYTES = 5 * 1024 * 1024   # 5 MB
_ROTATE_LINES = 10_000


def _summarize_jsonl(path: Path) -> dict[str, Any]:
    """Build a compact stats dict from a timeline-shaped JSONL file.

    Used when rotating a full `timeline.jsonl` into the archive so that
    `orchestration_history(include_archives=True)` can surface aggregate
    history without loading raw records into context.
    """
    summary: dict[str, Any] = {
        "covers":       {"from": None, "to": None},
        "record_count": 0,
        "per_project":  {},
        "per_agent":    {},
    }
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
                ts = r.get("ts") or ""
                if ts:
                    if not summary["covers"]["from"] or ts < summary["covers"]["from"]:
                        summary["covers"]["from"] = ts
                    if not summary["covers"]["to"]   or ts > summary["covers"]["to"]:
                        summary["covers"]["to"] = ts
                summary["record_count"] += 1
                proj = r.get("project") or "?"
                pstats = summary["per_project"].setdefault(proj, {
                    "dispatched": 0, "succeeded": 0, "failed": 0, "cancelled": 0,
                })
                evt = r.get("event")
                if evt == "dispatched":
                    pstats["dispatched"] += 1
                elif evt == "complete":
                    if r.get("ok"):
                        pstats["succeeded"] += 1
                    else:
                        pstats["failed"] += 1
                elif evt == "error":
                    pstats["failed"] += 1
                elif evt == "cancelled":
                    pstats["cancelled"] += 1
                agent = r.get("agent")
                if agent:
                    summary["per_agent"].setdefault(agent, {"events": 0})
                    summary["per_agent"][agent]["events"] += 1
    except Exception:
        pass
    return summary


def _rotate_now(path: Path) -> None:
    """Move current timeline.jsonl into archive/ and write a paired summary.

    Must be called inside `_timeline_lock`. Silent on failure — rotation
    is opportunistic; a missed rotation just delays the next attempt.
    """
    if not path.exists() or path.stat().st_size == 0:
        return
    # Microsecond-precision suffix so rapid back-to-back rotations (common
    # in tests that dial the threshold down) don't collide on `rename()`.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    d = archive_dir()
    d.mkdir(parents=True, exist_ok=True)
    archived = d / f"timeline-{ts}.jsonl"
    summary_path = d / f"timeline-{ts}-summary.json"
    try:
        summary = _summarize_jsonl(path)
        path.rename(archived)
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _maybe_rotate(path: Path) -> None:
    """Trigger a rotate if `path` exceeds size or line-count thresholds.

    Cheap size check first to avoid scanning every append; only counts
    lines if the byte threshold has been crossed (line threshold is
    mainly a safety net for pathological single-line-per-event
    workloads).
    """
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size >= _ROTATE_BYTES:
        _rotate_now(path)
        return
    # Only bother counting lines if we're within 25% of the line threshold
    # by byte-proxy (avoids an O(n) scan on every append for tiny files).
    if size < _ROTATE_BYTES // 4:
        return
    try:
        with path.open("rb") as fh:
            lines = sum(1 for _ in fh)
    except OSError:
        return
    if lines >= _ROTATE_LINES:
        _rotate_now(path)


def list_archives() -> list[Path]:
    """Return archived `timeline-*.jsonl` files, newest → oldest."""
    d = archive_dir()
    if not d.is_dir():
        return []
    return sorted(d.glob("timeline-*.jsonl"), reverse=True)


def read_archive_summary(archive_path: Path) -> dict[str, Any] | None:
    """Return the `*-summary.json` paired with an archive file, or None."""
    summary_path = archive_path.with_name(archive_path.stem + "-summary.json")
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None


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
            # Rotate on thresholds, still inside the process-level lock so
            # the rename never races a concurrent append in this process.
            _maybe_rotate(path)
    except Exception:
        pass
