"""PTY-backed Textual widget — agent REPL pass-through.

A `pty.openpty()` master/slave pair owned by the widget. The slave fd
is plumbed into the spawned agent CLI's stdin/stdout/stderr; the master
fd is drained asynchronously via `loop.add_reader` and the bytes are
fed into a `pyte.Screen`. Each refresh walks the screen buffer and
emits a `rich.text.Text` with per-cell styling.

When constructed with a `project=` argument, the widget doubles as a
dispatch event writer: `submit_prompt(text)` writes the prompt bytes
into the PTY and records `start` in `dispatches_db` + `events.jsonl`,
mirroring what MCP `dispatch()` does for a non-interactive child. A
screen-stability watcher then declares the dispatch `complete` once
the bottom rows of the pyte buffer hash-match for a few consecutive
ticks — this gives the sidebar (`DispatchWatcher`) and any external
observers the same lifecycle records they get from MCP-driven runs,
without paying the MCP round-trip latency.

Phase 0 limitations:
- Plain blocking write to master on key events (PTY buffers comfortably
  absorb a typical REPL keystroke rate).
- No mouse forwarding, no scrollback, no copy/paste integration.
- Cursor rendered as a reversed cell. Most agent CLIs draw their own
  cursor block via escape codes; pyte's tracker is the fallback.
- PTY-mode dispatches do not capture stdout into the `output` column
  of `dispatches.db` and do not emit per-chunk `output` events into
  `dispatch.jsonl`. Token totals are unavailable too. Both are tracked
  separately for a follow-up pass.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import re
import struct
import subprocess
import termios
import time
import uuid
from typing import Sequence

import pyte
from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.widget import Widget

from central_mcp import dispatches_db, events as dispatch_events, pty_sessions


# CSI sequences with `<` or `>` private-prefix bytes (Kitty keyboard
# protocol — `\x1b[<u`, `\x1b[>1u`, `\x1b[>4;2m`, `\x1b[>0q`, …) and
# xterm modify-other-keys / extended queries are emitted by claude on
# startup to probe terminal capabilities. pyte 0.8.2's CSI parser
# bails on those private prefixes and leaks the final byte (`u`, `q`)
# into the screen as a literal — the visible "u" stuck on the first
# line was always pyte mis-parsing this sequence. Strip them before
# pyte sees the byte stream; we don't respond to the queries either,
# which claude tolerates (it just falls back to the conservative
# default capability set).
_PRIVATE_CSI_LEAK_RE = re.compile(
    rb"\x1b\[[<>][\x30-\x3F]*[\x20-\x2F]*[\x40-\x7E]"
)


_DEFAULT_COLS = 100
_DEFAULT_ROWS = 30

# Keys reserved for the surrounding Textual chrome — never forwarded into
# the PTY child. Adding a key here means losing it for the embedded agent;
# keep the set minimal. Without this, `Ctrl+Q` lands inside claude (which
# does nothing visible) and the user has to terminate the agent first
# before our app-level quit binding can fire.
_CHROME_KEYS = frozenset({"ctrl+q"})

# Completion detection cadence. The watcher hashes (cursor pos + bottom
# 6 rows of the pyte buffer) every tick; once it matches the previous
# hash for `_STABLE_TICKS` consecutive ticks the dispatch is marked
# complete. 3 × 0.5s = 1.5s of uninterrupted screen state — long enough
# that streaming responses don't false-positive but short enough that a
# follow-up prompt feels responsive.
_TICK_SEC = 0.5
_STABLE_TICKS = 3
# How many bottom rows feed the stability hash. The whole screen is too
# noisy (status bars / clocks tick on their own); the bottom strip is
# where the agent's response and prompt indicator settle.
_HASH_TAIL_ROWS = 6

# Debug log — opt-in via CMCP_TUI_DEBUG=1. Writes one line per sizing
# event to ~/.central-mcp/tui-debug.log so we can verify the PTY child
# starts at the actual widget width (and that subsequent resizes line up).
def _debug(msg: str) -> None:
    if not os.environ.get("CMCP_TUI_DEBUG"):
        return
    try:
        from central_mcp import paths as _paths
        log = _paths.central_mcp_home() / "tui-debug.log"
        with log.open("a") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat(timespec='milliseconds')} {msg}\n")
    except Exception:
        pass


class PtyTerminal(Widget, can_focus=True):
    DEFAULT_CSS = """
    PtyTerminal {
        height: 1fr;
        width: 1fr;
        background: $surface;
        color: $text;
    }
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        project: str | None = None,
        agent: str | None = None,
        cwd: str | os.PathLike[str] | None = None,
    ) -> None:
        super().__init__()
        self.command = list(command)
        # Bind this terminal to a project so submit_prompt() can record
        # `start` / `complete` lifecycle events into dispatches.db and the
        # project's dispatch.jsonl. None → free-floating REPL (no tracking).
        self._project = project
        self._agent_name = agent or (self.command[0] if self.command else "")
        self._cwd = os.fspath(cwd) if cwd else None
        self._cols = _DEFAULT_COLS
        self._rows = _DEFAULT_ROWS
        self._screen = pyte.Screen(self._cols, self._rows)
        self._stream = pyte.ByteStream(self._screen)
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None
        # Active-dispatch state. `_active_did` is set by submit_prompt()
        # and cleared by _mark_complete(); the completion watcher only
        # runs while a dispatch is in flight.
        self._active_did: str | None = None
        self._active_started_at: float = 0.0
        self._completion_task: asyncio.Task | None = None

    # ── lifecycle ────────────────────────────────────────────────────

    def on_mount(self) -> None:
        # Defer spawn until after the first layout pass so we know the
        # actual widget size. Spawning at on_mount time gives claude the
        # default 100×30 winsize and freezes its banner / table borders
        # / decorative underlines at that width — by the time SIGWINCH
        # arrives the visual damage is already in pyte's buffer. Using
        # on_resize directly is also unsafe because it can fire with a
        # (0, 0) intermediate size and spawn claude into a TTY too small
        # for claude to render anything (it exits immediately).
        self.call_after_refresh(self._spawn_when_sized)

    def _spawn_when_sized(self) -> None:
        if self._master_fd is not None:
            return
        size = self.size
        if size.width < 20 or size.height < 5:
            # Layout still settling — try again on the next refresh.
            self.call_after_refresh(self._spawn_when_sized)
            return
        self._spawn_at(size)

    def on_unmount(self) -> None:
        if self._completion_task is not None and not self._completion_task.done():
            self._completion_task.cancel()
            self._completion_task = None
        # If a dispatch was still in flight when the user closed the
        # widget, mark it cancelled so the sidebar doesn't show a
        # zombie "running" row forever.
        if self._active_did is not None:
            self._mark_complete(ok=False, status="cancelled")
        # Drop the PTY session registration so `dispatch()` resumes
        # accepting background calls into this project.
        if self._project is not None:
            pty_sessions.unregister(self._project)
        self._teardown_reader()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass

    def _spawn(self) -> None:
        master_fd, slave_fd = pty.openpty()
        self._set_winsize(slave_fd, self._rows, self._cols)
        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
        }
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                preexec_fn=os.setsid,
                env=env,
                cwd=self._cwd,
            )
        finally:
            os.close(slave_fd)
        os.set_blocking(master_fd, False)
        self._master_fd = master_fd

    # ── PTY → screen ─────────────────────────────────────────────────

    def _on_pty_readable(self) -> None:
        if self._master_fd is None:
            return
        try:
            data = os.read(self._master_fd, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._teardown_reader()
            return
        if not data:
            self._teardown_reader()
            return
        # CMCP_TUI_DUMP_PTY=1 → append every chunk to ~/.central-mcp/
        # tui-pty.bin so we can hexdump and identify control sequences
        # pyte fails to parse cleanly (e.g. stray `u`).
        if os.environ.get("CMCP_TUI_DUMP_PTY"):
            try:
                from central_mcp import paths as _paths
                with (_paths.central_mcp_home() / "tui-pty.bin").open("ab") as f:
                    f.write(data)
            except Exception:
                pass
        clean = _PRIVATE_CSI_LEAK_RE.sub(b"", data)
        self._stream.feed(clean)
        self.refresh()

    def _teardown_reader(self) -> None:
        if self._master_fd is None:
            return
        try:
            asyncio.get_event_loop().remove_reader(self._master_fd)
        except (ValueError, RuntimeError):
            pass

    # ── input → PTY ──────────────────────────────────────────────────

    async def on_key(self, event: events.Key) -> None:
        if self._master_fd is None:
            return
        if event.key in _CHROME_KEYS:
            # Bubble up so the App's BINDINGS (e.g. ctrl+q → quit) fire.
            return
        data = _key_to_bytes(event)
        if not data:
            return
        try:
            os.write(self._master_fd, data)
        except OSError:
            return
        event.stop()
        event.prevent_default()

    # ── dispatch lifecycle ───────────────────────────────────────────

    def submit_prompt(self, text: str) -> str | None:
        """Send `text` to the running REPL as a new prompt.

        When this widget is bound to a project, the call also records a
        `start` row in `dispatches.db` and a `start` event in the
        project's `dispatch.jsonl`, then arms the screen-stability
        watcher to mark the dispatch complete when the agent's output
        settles. Returns the dispatch_id when tracking was started, or
        None when the PTY isn't ready / no project is bound / a previous
        dispatch is still in flight (in which case the bytes are still
        written so the user can answer follow-up questions).
        """
        if self._master_fd is None:
            return None
        try:
            os.write(self._master_fd, text.encode("utf-8") + b"\r")
        except OSError:
            return None
        if self._project is None or self._active_did is not None:
            return None

        did = uuid.uuid4().hex[:8]
        self._active_did = did
        self._active_started_at = time.time()
        try:
            dispatches_db.upsert_started({
                "id": did,
                "project": self._project,
                "agent": self._agent_name,
                "status": "running",
                "started": self._active_started_at,
                "prompt": text,
                "command": " ".join(self.command),
                "chain": [self._agent_name],
            })
            dispatch_events.log_event(
                self._project, did, "start",
                agent=self._agent_name,
                prompt=text,
                mode="pty",
                chain=[self._agent_name],
            )
            dispatch_events.log_timeline(
                did, self._project, "dispatched",
                agent=self._agent_name,
                mode="pty",
            )
        except Exception:
            # `events`/`dispatches_db` are documented as best-effort, but
            # belt-and-braces here so a misconfigured home dir never
            # tears down the TUI mid-keystroke.
            pass
        return did

    def _screen_hash(self) -> int:
        """Hash the cursor position + bottom rows of the pyte buffer.

        This is the signal the completion watcher uses to detect "the
        agent has stopped writing." Top rows are excluded because some
        agents redraw status decoration there on a timer; the bottom
        strip is where actual response text and the input prompt land.
        """
        sc = self._screen
        cur = (sc.cursor.y, sc.cursor.x, sc.cursor.hidden)
        rows: list[str] = []
        start = max(0, sc.lines - _HASH_TAIL_ROWS)
        for y in range(start, sc.lines):
            row = sc.buffer[y]
            rows.append(
                "".join((row[x].data or " ") for x in range(sc.columns))
            )
        return hash((cur, tuple(rows)))

    async def _completion_watcher(self) -> None:
        """Mark `_active_did` complete once the screen settles.

        Idle when no dispatch is active. When one is in flight, the
        watcher hashes the screen every `_TICK_SEC`; once the hash has
        matched the previous tick for `_STABLE_TICKS` consecutive ticks
        the dispatch is finalised. The PTY child keeps running — only
        the bookkeeping closes — so the user can immediately submit a
        follow-up prompt.
        """
        last_hash: int | None = None
        stable = 0
        try:
            while self._master_fd is not None:
                await asyncio.sleep(_TICK_SEC)
                if self._active_did is None:
                    last_hash = None
                    stable = 0
                    continue
                h = self._screen_hash()
                if h == last_hash:
                    stable += 1
                else:
                    stable = 0
                last_hash = h
                if stable >= _STABLE_TICKS:
                    self._mark_complete(ok=True, status="complete")
                    last_hash = None
                    stable = 0
        except asyncio.CancelledError:
            pass

    def _mark_complete(self, *, ok: bool, status: str) -> None:
        did = self._active_did
        if did is None or self._project is None:
            self._active_did = None
            return
        duration = round(time.time() - self._active_started_at, 1)
        self._active_did = None
        try:
            dispatches_db.upsert_finished(did, status, {
                "ok": ok,
                "duration_sec": duration,
                "exit_code": 0 if ok else None,
                "output": "",
                "stderr": "",
                "tokens": None,
                "agent_used": self._agent_name,
            })
            dispatch_events.log_event(
                self._project, did, "complete",
                agent_used=self._agent_name,
                ok=ok,
                status=status,
                duration_sec=duration,
                mode="pty",
            )
            dispatch_events.log_timeline(
                did, self._project, "complete",
                agent=self._agent_name,
                ok=ok,
                duration_sec=duration,
                mode="pty",
            )
        except Exception:
            pass

    # ── resize ───────────────────────────────────────────────────────

    def on_resize(self, event: events.Resize) -> None:
        # Spawn happens via on_mount → call_after_refresh; this handler
        # only forwards subsequent size changes. Spawning here would race
        # with the deferred path and intermediate (0, 0) sizes.
        if self._master_fd is None:
            return
        self._apply_size(event.size)

    def _spawn_at(self, size: Size) -> None:
        cols = max(20, size.width)
        rows = max(5, size.height)
        self._cols, self._rows = cols, rows
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.ByteStream(self._screen)
        self._spawn()
        _debug(f"_spawn_at cols={cols} rows={rows} size={size!r} master_fd={self._master_fd}")
        # Register the PTY session so `dispatch()` knows the project is
        # in PTY mode and refuses background prompts that would race the
        # human user driving the pane. Free-floating REPLs (no project)
        # are not registered.
        if (
            self._project is not None
            and self._proc is not None
            and self._proc.poll() is None
        ):
            pty_sessions.register(
                self._project, self._proc.pid, self._agent_name
            )
        if self._master_fd is not None:
            loop = asyncio.get_running_loop()
            loop.add_reader(self._master_fd, self._on_pty_readable)
            # The completion watcher only starts when this widget is
            # bound to a project — without one there's nowhere to record
            # `start` / `complete` events, so the watcher would have
            # nothing to do.
            if self._project is not None:
                self._completion_task = loop.create_task(
                    self._completion_watcher()
                )

    def _apply_size(self, size: Size) -> None:
        cols = max(20, size.width)
        rows = max(5, size.height)
        if cols == self._cols and rows == self._rows:
            return
        _debug(f"_apply_size cols={cols} rows={rows} (was {self._cols}x{self._rows})")
        self._cols, self._rows = cols, rows
        try:
            self._screen.resize(lines=rows, columns=cols)
        except Exception:
            pass
        if self._master_fd is not None:
            try:
                self._set_winsize(self._master_fd, rows, cols)
            except OSError:
                pass
        self.refresh()

    @staticmethod
    def _set_winsize(fd: int, rows: int, cols: int) -> None:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    # ── render ───────────────────────────────────────────────────────

    def render(self) -> Text:
        screen = self._screen
        cur_y, cur_x = screen.cursor.y, screen.cursor.x
        cursor_visible = not screen.cursor.hidden
        text = Text(no_wrap=True, overflow="crop")
        cursor_overlay = Style(reverse=True)
        for y in range(screen.lines):
            row = screen.buffer[y]
            for x in range(screen.columns):
                ch = row[x]
                style = _pyte_char_style(ch)
                if cursor_visible and y == cur_y and x == cur_x:
                    style = (style + cursor_overlay) if style else cursor_overlay
                text.append(ch.data or " ", style=style)
            if y < screen.lines - 1:
                text.append("\n")
        return text


# ── helpers ──────────────────────────────────────────────────────────

def _pyte_char_style(ch) -> Style | None:
    fg = _pyte_color(ch.fg)
    bg = _pyte_color(ch.bg)
    is_blank = not ch.data or ch.data.isspace()
    # Drop text-emphasis attributes on blank cells: terminals retain the
    # active SGR state even when nothing was actually typed there, so a
    # hyperlink-underlined run followed by spaces (or claude's tool-result
    # separators) leaves underscore=True on empty cells. Rendering those
    # as Rich `underline` produces visible runs of `_` glyphs that read
    # as long horizontal lines in our widget. Keep color/reverse so
    # background highlights still survive.
    bold = ch.bold and not is_blank
    italic = ch.italics and not is_blank
    underline = ch.underscore and not is_blank
    strike = ch.strikethrough and not is_blank
    reverse = bool(ch.reverse)
    if (
        fg is None
        and bg is None
        and not bold
        and not italic
        and not underline
        and not reverse
        and not strike
    ):
        return None
    return Style(
        color=fg,
        bgcolor=bg,
        bold=bold or None,
        italic=italic or None,
        underline=underline or None,
        reverse=reverse or None,
        strike=strike or None,
    )


def _pyte_color(c: str) -> str | None:
    if not c or c == "default":
        return None
    if c.startswith("bright"):
        return "bright_" + c[len("bright"):]
    if len(c) == 6 and all(d in "0123456789abcdefABCDEF" for d in c):
        return "#" + c.lower()
    return c


def _key_to_bytes(event: events.Key) -> bytes:
    """Translate a Textual key event into the bytes a PTY child expects."""
    key = event.key
    char = event.character
    table = {
        "enter":     b"\r",
        "tab":       b"\t",
        "backspace": b"\x7f",
        "escape":    b"\x1b",
        "up":        b"\x1b[A",
        "down":      b"\x1b[B",
        "right":     b"\x1b[C",
        "left":      b"\x1b[D",
        "home":      b"\x1b[H",
        "end":       b"\x1b[F",
        "delete":    b"\x1b[3~",
        "insert":    b"\x1b[2~",
        "pageup":    b"\x1b[5~",
        "pagedown":  b"\x1b[6~",
        "f1":  b"\x1bOP", "f2":  b"\x1bOQ",
        "f3":  b"\x1bOR", "f4":  b"\x1bOS",
        "f5":  b"\x1b[15~", "f6":  b"\x1b[17~",
        "f7":  b"\x1b[18~", "f8":  b"\x1b[19~",
        "f9":  b"\x1b[20~", "f10": b"\x1b[21~",
        "f11": b"\x1b[23~", "f12": b"\x1b[24~",
    }
    if key in table:
        return table[key]
    if key.startswith("ctrl+") and len(key) == 6:
        letter = key[5]
        if "a" <= letter <= "z":
            return bytes([ord(letter) - ord("a") + 1])
    if char and len(char) >= 1:
        return char.encode("utf-8")
    return b""
