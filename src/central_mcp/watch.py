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

import curses
import json
import queue
import re
import sys
import threading
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


# ── Curses-based watch (TTY mode) ────────────────────────────────────────────

_HEADER_HEIGHT = 4  # lines reserved for the fixed status header


def _curses_draw_header(
    win: "curses.window",
    project: str,
    hstate: dict[str, Any],
) -> None:
    """Redraw the fixed header window from current hstate."""
    win.erase()
    _r, c = win.getmaxyx()

    # Line 0: project + agent identity
    agent = hstate.get("agent") or "—"
    title = f" central-mcp │ {project} │ agent: {agent}"
    try:
        win.addstr(0, 0, title[: c - 1], curses.A_BOLD | curses.color_pair(1))
    except curses.error:
        pass

    # Line 1: current running status
    active: set = hstate.get("active_dids", set())
    if active:
        did = next(iter(active))[:8]
        elapsed = time.time() - hstate.get("started_at", time.time())
        s = f" ↻ running [{did}] +{elapsed:.0f}s"
        if len(active) > 1:
            s += f" (+{len(active) - 1} more)"
        attr = curses.A_BOLD | curses.color_pair(4)  # yellow
    else:
        last_ok = hstate.get("last_ok")
        if last_ok is True:
            s = " ✓ idle"
            attr = curses.color_pair(2)  # green
        elif last_ok is False:
            s = " ✗ idle (last failed)"
            attr = curses.color_pair(3)  # red
        else:
            s = " — idle"
            attr = curses.A_DIM
    try:
        win.addstr(1, 0, s[: c - 1], attr)
    except curses.error:
        pass

    # Line 2: last dispatch summary
    last = hstate.get("last", "")
    if last:
        try:
            win.addstr(2, 0, f" Last: {last}"[: c - 1], curses.A_DIM)
        except curses.error:
            pass

    # Line 3: separator
    try:
        win.addstr(3, 0, "─" * (c - 1), curses.A_DIM)
    except curses.error:
        pass

    win.noutrefresh()


def _curses_watch(
    stdscr: "curses.window",
    project: str,
    path: Path,
    from_start: bool,
) -> None:
    """Curses main loop: fixed 4-line header + scrolling log region."""
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)

    rows, cols = stdscr.getmaxyx()
    header_win = curses.newwin(_HEADER_HEIGHT, cols, 0, 0)
    log_win = curses.newwin(rows - _HEADER_HEIGHT, cols, _HEADER_HEIGHT, 0)
    log_win.scrollok(True)
    log_win.idlok(True)

    hstate: dict[str, Any] = {
        "agent": "",
        "active_dids": set(),
        "started_at": 0.0,
        "last_ok": None,
        "last": "",
    }
    states: dict[str, _DispatchState] = {}
    rq: queue.Queue = queue.Queue()

    def _reader() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
        f = path.open("r")
        if not from_start:
            f.seek(0, 2)
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.15)
                    try:
                        if path.stat().st_size < f.tell():
                            f.close()
                            f = path.open("r")
                    except FileNotFoundError:
                        pass
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    rq.put(json.loads(line))
                except json.JSONDecodeError:
                    rq.put({"_raw": line})
        finally:
            try:
                f.close()
            except Exception:
                pass

    threading.Thread(target=_reader, daemon=True).start()

    def _wlog(text: str, attr: int = 0) -> None:
        try:
            log_win.addstr(text, attr)
            log_win.noutrefresh()
        except curses.error:
            pass

    def _process(record: dict[str, Any]) -> None:
        if "_raw" in record:
            _wlog(f"(unparseable: {record['_raw'][:60]!r})\n", curses.A_DIM)
            return

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
            hstate["agent"] = agent
            hstate["active_dids"].add(did)
            hstate["started_at"] = state.started_at
            chain = record.get("chain") or []
            prompt = record.get("prompt", "")
            _wlog(f"\n── {ts} [{did}] start ──\n",
                  curses.A_BOLD | curses.color_pair(1))
            if agent:
                _wlog(f"agent: {agent}\n", curses.A_BOLD)
            if len(chain) > 1:
                _wlog(f"chain: {' → '.join(chain)}\n", curses.A_DIM)
            if prompt:
                _wlog("> ", curses.A_BOLD)
                _wlog(prompt + "\n")
            _wlog("\n")

        elif event == "attempt_start":
            _wlog(f"↻ {ts}  fallback → {agent}\n", curses.color_pair(4))

        elif event == "output":
            chunk = record.get("chunk", "")
            stream = record.get("stream", "stdout")
            if _FENCE_RE.match(chunk):
                state.in_code_block = not state.in_code_block
            if state.started_at and not state.done:
                elapsed = time.time() - state.started_at
                prefix, p_attr = f"+{elapsed:4.0f}s ", curses.A_DIM
            else:
                prefix, p_attr = "       ", 0
            if stream == "stderr":
                _wlog(prefix, p_attr)
                _wlog(chunk + "\n", curses.color_pair(3))
            elif state.in_code_block:
                _wlog(prefix, p_attr)
                _wlog(chunk + "\n", curses.color_pair(5))
            elif _is_spinner(chunk):
                return  # no prefix written yet — safe to skip entirely
            else:
                noise = _agent_noise(chunk, state.agent)
                _wlog(prefix, p_attr)
                _wlog(chunk + "\n", curses.A_DIM if noise == "dim" else 0)

        elif event == "complete":
            state.done = True
            ok = record.get("ok")
            status = record.get("status", "complete")
            dur = record.get("duration_sec")
            tokens = record.get("tokens")
            used = record.get("agent_used") or agent or ""
            exit_code = record.get("exit_code")
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
            hstate["active_dids"].discard(did)
            hstate["last_ok"] = bool(ok)
            if ok:
                badge, badge_attr = "✓ done", curses.color_pair(2) | curses.A_BOLD
            elif status == "timeout":
                badge, badge_attr = "⚠ timeout", curses.color_pair(4) | curses.A_BOLD
            elif status == "cancelled":
                badge, badge_attr = "⚠ cancelled", curses.color_pair(4) | curses.A_BOLD
            else:
                badge, badge_attr = "✗ failed", curses.color_pair(3) | curses.A_BOLD
            hstate["last"] = f"{badge} ({summary})" if summary else badge
            _wlog(f"\n── {ts} [{did}] ", curses.A_BOLD | curses.color_pair(1))
            _wlog(badge, badge_attr)
            if summary:
                _wlog(f" ({summary})")
            _wlog(" ──\n\n", curses.A_BOLD | curses.color_pair(1))
            err = record.get("error")
            if err and not ok:
                _wlog(f"error: {err}\n", curses.color_pair(3))

        elif event == "error":
            state.done = True
            err = record.get("error", "unknown error")
            hstate["active_dids"].discard(did)
            hstate["last_ok"] = False
            _wlog(f"\n── {ts} [{did}] ✗ error: {err} ──\n\n",
                  curses.color_pair(3))

    # Initial draw
    _curses_draw_header(header_win, project, hstate)
    _wlog(f"(watching {path}\n waiting for dispatches — press q to quit)\n\n",
          curses.A_DIM)
    curses.doupdate()

    last_tick = 0.0
    while True:
        try:
            while True:
                _process(rq.get_nowait())
        except queue.Empty:
            pass

        now = time.time()
        if now - last_tick >= 0.5:
            _curses_draw_header(header_win, project, hstate)
            last_tick = now
            curses.doupdate()

        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27, 3):  # q / Q / ESC / Ctrl+C
            break
        if key == curses.KEY_RESIZE:
            rows, cols = stdscr.getmaxyx()
            header_win.resize(_HEADER_HEIGHT, cols)
            log_win.resize(rows - _HEADER_HEIGHT, cols)
            log_win.mvwin(_HEADER_HEIGHT, 0)
            _curses_draw_header(header_win, project, hstate)
            log_win.refresh()
            curses.doupdate()

        time.sleep(0.05)


def run(project: str, *, from_start: bool = False) -> int:
    """Follow the dispatch log for one project. Blocks until Ctrl+C."""
    path = events.log_path(project)
    if sys.stdout.isatty():
        try:
            curses.wrapper(_curses_watch, project, path, from_start)
        except KeyboardInterrupt:
            pass
        return 0
    # Non-TTY fallback (piped output, CI, tests)
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
