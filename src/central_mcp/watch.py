"""`central-mcp watch <project>` — stream one project's dispatch events.

Tails `~/.central-mcp/logs/<project>/dispatch.jsonl` and renders each
event as human-readable text with ANSI colors. This is what the tmux
observation pane runs instead of the agent's interactive CLI so users
see dispatch activity live without having to poll MCP tools.

Quiet exit on SIGINT (Ctrl+C) or broken pipe (terminal closed). If the
log file doesn't exist yet, waits for dispatch to create it rather
than erroring out — fresh projects should show an empty pane that
lights up on the first dispatch.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from central_mcp import events

# ANSI color helpers — gracefully no-op when stdout isn't a TTY.
_IS_TTY = sys.stdout.isatty()


def _c(color: str, text: str) -> str:
    if not _IS_TTY:
        return text
    return f"\x1b[{color}m{text}\x1b[0m"


DIM     = lambda s: _c("2", s)
BOLD    = lambda s: _c("1", s)
RED     = lambda s: _c("31", s)
GREEN   = lambda s: _c("32", s)
YELLOW  = lambda s: _c("33", s)
BLUE    = lambda s: _c("34", s)
CYAN    = lambda s: _c("36", s)
MAGENTA = lambda s: _c("35", s)


def _fmt_ts(ts: str) -> str:
    """Turn an ISO timestamp into a compact HH:MM:SS for pane display."""
    if not ts:
        return "         "
    return ts[11:19] if "T" in ts else ts[:8]


# Spinner / progress-bar lines to skip entirely — not content.
# Conservative: only Unicode braille spinners and explicit bracket progress bars.
# ASCII-only patterns (----, |, /) are excluded — too many false positives
# (codex uses "--------" separators; pipes appear in tables and code).
_SPINNER_RE = re.compile(
    r"^\s*(?:"
    r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷][⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷\s]*"  # braille spinners
    r"|\[[\s=#>·\-\.]+\]\s*(?:\d+%)?"  # [####   ] bracket progress
    r"|\d+%"  # bare percentage
    r")\s*$"
)

# Opening ``` / ~~~ fences.
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")

# Agent-specific metadata patterns — rendered DIM (informational, not agent output).
# Codex header block that appears before actual response: workdir, model, provider, session id.
_CODEX_META_RE = re.compile(
    r"^\s*(?:workdir|model|provider|session\s+id)\s*:", re.IGNORECASE
)
# Codex "--------" separator lines (not spinners, but structural dividers).
_CODEX_SEP_RE = re.compile(r"^\s*-{4,}\s*$")

# Gemini status lines printed to stdout before/after the model response.
_GEMINI_META_RE = re.compile(
    r"^\s*(?:"
    r"\[WARN\]"              # Gemini warning prefix
    r"|YOLO mode is enabled" # permission mode banner
    r"|Gemini\s+\S+\s+\(model:"  # version banner e.g. "Gemini 2.5 (model: gemini-..."
    r")",
    re.IGNORECASE,
)


def _is_spinner(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False  # blank lines are intentional spacing, not noise
    return bool(_SPINNER_RE.match(stripped))


def _agent_noise(line: str, agent: str) -> str | None:
    """Return 'dim' if this line is agent-specific metadata noise, else None."""
    stripped = line.strip()
    if not stripped:
        return None
    a = agent.lower()
    if "codex" in a:
        if _CODEX_META_RE.match(stripped) or _CODEX_SEP_RE.match(stripped):
            return "dim"
    elif "gemini" in a:
        if _GEMINI_META_RE.match(stripped):
            return "dim"
    return None


@dataclass
class _DispatchState:
    started_at: float = 0.0
    in_code_block: bool = False
    done: bool = False
    agent: str = ""


def _render(
    record: dict[str, Any],
    out: TextIO,
    states: dict[str, _DispatchState] | None = None,
) -> None:
    if states is None:
        states = {}

    event = record.get("event", "?")
    ts = _fmt_ts(record.get("ts", ""))
    did = record.get("id", "????????")
    agent = record.get("agent") or record.get("agent_used") or ""
    state = states.setdefault(did, _DispatchState())

    if event == "start":
        state.started_at = time.time()
        state.in_code_block = False
        state.done = False
        state.agent = agent
        header = BOLD(CYAN(f"── {ts} [{did}] start ──"))
        out.write(f"\n{header}\n")
        if agent:
            out.write(BOLD(f"agent: {agent}") + "\n")
        chain = record.get("chain") or []
        if len(chain) > 1:
            out.write(DIM(f"chain: {' → '.join(chain)}\n"))
        prompt = record.get("prompt", "")
        if prompt:
            out.write(f"{BOLD('>')} {prompt}\n")
        out.write("\n")

    elif event == "attempt_start":
        out.write(YELLOW(f"↻ {ts}  fallback → {agent}\n"))

    elif event == "output":
        chunk = record.get("chunk", "")
        stream = record.get("stream", "stdout")

        # Toggle code-block state on fence markers.
        if _FENCE_RE.match(chunk):
            state.in_code_block = not state.in_code_block

        # Elapsed prefix during active dispatch.
        if state.started_at and not state.done:
            elapsed = time.time() - state.started_at
            prefix = DIM(f"+{elapsed:4.0f}s ")
        else:
            prefix = "       "

        if stream == "stderr":
            out.write(prefix + RED(chunk) + "\n")
        elif state.in_code_block:
            out.write(prefix + MAGENTA(chunk) + "\n")
        elif _is_spinner(chunk):
            return  # skip spinners and progress bars silently
        else:
            noise = _agent_noise(chunk, state.agent)
            if noise == "dim":
                out.write(prefix + DIM(chunk) + "\n")
            else:
                out.write(prefix + chunk + "\n")

    elif event == "complete":
        state.done = True
        ok = record.get("ok")
        status = record.get("status", "complete")
        exit_code = record.get("exit_code")
        dur = record.get("duration_sec")
        tokens = record.get("tokens")
        used = record.get("agent_used") or agent or ""
        bits = []
        if used:
            bits.append(used)
        if dur is not None:
            bits.append(f"{dur}s")
        if exit_code is not None:
            bits.append(f"exit={exit_code}")
        if tokens:
            total = tokens.get("total") or (
                (tokens.get("input") or 0) + (tokens.get("output") or 0)
            )
            if total:
                bits.append(f"tokens={total:,}")
        summary = " · ".join(bits)
        if ok:
            badge = GREEN("✓ done")
        elif status == "timeout":
            badge = YELLOW("⚠ timeout")
        elif status == "cancelled":
            badge = YELLOW("⚠ cancelled")
        else:
            badge = RED("✗ failed")
        err = record.get("error")
        footer = f"── {ts} [{did}] {badge}"
        if summary:
            footer += f" ({summary})"
        footer += " " + BOLD(CYAN("─" * 2))
        out.write(f"\n{footer}\n")
        if err and not ok:
            out.write(RED(f"error: {err}") + "\n")
        out.write("\n")

    elif event == "error":
        state.done = True
        err = record.get("error", "unknown error")
        out.write(RED(f"\n── {ts} [{did}] ✗ error: {err} ──\n\n"))

    out.flush()


def _tail_forever(path: Path, from_start: bool) -> None:
    """Follow a jsonl file, rendering each record as it arrives.

    Handles file rotation/truncation by re-opening if the inode or size
    changes in ways that suggest the file was replaced.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()

    f = path.open("r")
    if not from_start:
        f.seek(0, 2)

    states: dict[str, _DispatchState] = {}

    try:
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.15)
                try:
                    current_size = path.stat().st_size
                    if current_size < f.tell():
                        f.close()
                        f = path.open("r")
                except FileNotFoundError:
                    pass
                continue
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                sys.stdout.write(DIM(f"(unparseable log line: {line[:80]!r})\n"))
                sys.stdout.flush()
                continue
            _render(record, sys.stdout, states)
    finally:
        try:
            f.close()
        except Exception:
            pass


def run(project: str, *, from_start: bool = False) -> int:
    """Follow the dispatch log for one project. Blocks until Ctrl+C."""
    path = events.log_path(project)
    try:
        header = BOLD(CYAN(f"[central-mcp watch] {project} → {path}"))
        sys.stdout.write(header + "\n")
        sys.stdout.write(DIM("(streaming — waiting for dispatches)\n\n"))
        sys.stdout.flush()
        _tail_forever(path, from_start=from_start)
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        return 0
    return 0
