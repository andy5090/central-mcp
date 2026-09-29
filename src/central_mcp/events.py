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
from typing import Any, Collection, Iterator

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


def read_jsonl(
    path: Path,
    *,
    only_events: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    """Read a jsonl file written by this module into a list of records.

    Skips unparseable lines rather than failing — a partially written
    final line is normal for a log that is appended to concurrently.
    Returns [] for a missing or unreadable file.

    `only_events` keeps just the records whose `event` is in the given
    set. Beyond filtering, it skips the JSON parse entirely for lines
    that cannot match, via a substring test against the exact
    serialization `log_event` emits. That matters because a project's
    dispatch log is dominated by per-line `output` chunks and grows
    without bound (these files reach tens of MB in a working install),
    while every reader here wants only the handful of lifecycle
    records. The test lives in this module deliberately: it depends on
    the writer's format, so both sides stay in one file.

    The pre-filter can only produce false positives — a prompt
    containing the literal marker text — and those are dropped by the
    exact check after parsing. A genuine record can never be missed,
    because `json.dumps` always emits the marker verbatim.
    """
    try:
        if not path.exists():
            return []
        raw = path.read_text(errors="replace")
    except OSError:
        return []

    markers = (
        tuple(f'"event": "{e}"' for e in only_events)
        if only_events is not None
        else ()
    )
    wanted = frozenset(only_events) if only_events is not None else None

    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if markers and not any(m in line for m in markers):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if wanted is not None and record.get("event") not in wanted:
            continue
        out.append(record)
    return out


# ---------- tailing one dispatch's output ----------

#: Writers stamp `ts` before they append, so two threads can land a few
#: milliseconds out of order. The backward scan keeps going this far past
#: its lower bound before it concludes nothing older can match.
_TAIL_SLACK_SEC = 2.0

_TAIL_BLOCK = 64 * 1024

_TS_PREFIX = b'{"ts": "'


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _lines_reversed(path: Path) -> Iterator[bytes]:
    """Yield a file's lines last-to-first without reading the whole file.

    Project logs are dominated by output chunks and reach tens of MB; a
    caller polling a running dispatch wants the last few hundred lines.
    """
    with path.open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        carry = b""
        while pos > 0:
            step = min(_TAIL_BLOCK, pos)
            pos -= step
            f.seek(pos)
            pieces = (f.read(step) + carry).split(b"\n")
            # The first piece may be the tail end of a line that starts in
            # the previous block — hold it until that block is read.
            carry = pieces[0]
            for piece in reversed(pieces[1:]):
                if piece:
                    yield piece
        if carry:
            yield carry


def _line_ts(line: bytes) -> datetime | None:
    """A record's timestamp without parsing the record.

    `log_event` always writes `ts` first, so it can be sliced out. Depends
    on the writer's format, which is why it lives next to the writer.
    """
    if not line.startswith(_TS_PREFIX):
        return None
    end = line.find(b'"', len(_TS_PREFIX))
    if end < 0:
        return None
    return _parse_ts(line[len(_TS_PREFIX):end].decode("ascii", errors="replace"))


def parse_cursor(since: str | None) -> tuple[datetime | None, int | None]:
    """Split a tail cursor into `(timestamp, already_delivered_at_it)`.

    A cursor from `tail_output` is `<ts>#<n>`: n output lines stamped
    exactly `ts` were already delivered. Timestamps have millisecond
    precision and output arrives in bursts, so a bare timestamp cannot say
    where inside one millisecond the previous read stopped — it would
    either repeat lines or drop them.

    A bare timestamp is accepted too, for a caller that has none of ours;
    it means "strictly after", returned as a count of None.
    """
    if not since:
        return None, 0
    ts_part, sep, count_part = since.partition("#")
    ts = _parse_ts(ts_part.strip())
    if ts is None:
        return None, 0
    if not sep:
        return ts, None
    try:
        return ts, max(0, int(count_part))
    except ValueError:
        return ts, None


def tail_output(
    project: str,
    dispatch_id: str,
    *,
    since: str | None = None,
    not_before: datetime | None = None,
    max_lines: int = 200,
    max_chunk_chars: int = 2000,
) -> dict[str, Any]:
    """Output lines one dispatch has emitted since a cursor.

    Reads the project log backward and stops at the lower bound, so the
    cost follows the amount of new output, not the size of the log.
    `not_before` (the dispatch's start) bounds the first read, when there
    is no cursor yet.

    Returns the newest `max_lines` lines oldest-first, how many older new
    lines were left out (`skipped`), and `next_since` — the cursor to pass
    on the next call. With no new output `next_since` is the cursor that
    came in, so a caller can pass it back unchanged.

    Only the live log is read. Output written before a log rotation is
    not returned.
    """
    empty = {"lines": [], "skipped": 0, "next_since": since}
    path = log_path(project)
    cursor_ts, delivered = parse_cursor(since)
    lower = cursor_ts or not_before
    id_marker = f'"id": "{dispatch_id}"'.encode()
    event_marker = b'"event": "output"'

    matched: list[tuple[datetime, dict[str, Any]]] = []  # newest first
    try:
        if not path.exists():
            return empty
        for line in _lines_reversed(path):
            ts = _line_ts(line)
            if ts is not None and lower is not None:
                if (lower - ts).total_seconds() > _TAIL_SLACK_SEC:
                    break
            if id_marker not in line or event_marker not in line:
                continue
            try:
                record = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue  # a half-written final line; the next call gets it
            if (
                not isinstance(record, dict)
                or record.get("id") != dispatch_id
                or record.get("event") != "output"
            ):
                continue
            rec_ts = _parse_ts(record.get("ts"))
            if rec_ts is None:
                continue
            if cursor_ts is not None and rec_ts < cursor_ts:
                continue
            matched.append((rec_ts, record))
    except OSError:
        return empty

    matched.reverse()  # oldest first, file order preserved within a timestamp
    if not matched:
        return empty

    newest_ts = matched[-1][0]
    at_newest = sum(1 for ts, _ in matched if ts == newest_ts)

    fresh: list[dict[str, Any]] = []
    seen_at_cursor = 0
    for ts, record in matched:
        if cursor_ts is not None and ts == cursor_ts:
            seen_at_cursor += 1
            if delivered is None or seen_at_cursor <= delivered:
                continue
        fresh.append(record)

    next_since = f"{matched[-1][1]['ts']}#{at_newest}"
    if not fresh:
        return {"lines": [], "skipped": 0, "next_since": next_since}

    limit = max(1, int(max_lines))
    skipped = max(0, len(fresh) - limit)
    lines = []
    for record in fresh[-limit:]:
        text = str(record.get("chunk") or "")
        cut = len(text) > max_chunk_chars
        lines.append({
            "ts": record.get("ts"),
            "stream": record.get("stream"),
            "agent": record.get("agent"),
            "text": text[:max_chunk_chars] if cut else text,
            "truncated": cut,
        })
    return {"lines": lines, "skipped": skipped, "next_since": next_since}


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
