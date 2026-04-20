"""Thin tmux CLI wrappers used by the optional observation layer.

Everything in here is for `central-mcp up` / `central-mcp down` — the
MCP dispatch path no longer depends on tmux at all. Kept minimal on
purpose: create a session, split off more panes, kill a session. No
send-keys, no pipe-pane, no process introspection.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class TmuxResult:
    ok: bool
    stdout: str
    stderr: str


def _run(args: list[str]) -> TmuxResult:
    try:
        proc = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return TmuxResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except FileNotFoundError:
        return TmuxResult(ok=False, stdout="", stderr="tmux not installed")


def has_session(name: str) -> bool:
    return _run(["has-session", "-t", name]).ok


def new_session(name: str, window: str, cwd: str, command: str | None = None) -> TmuxResult:
    args = ["new-session", "-d", "-s", name, "-n", window, "-c", cwd]
    if command:
        args.append(command)
    return _run(args)


def new_window(session: str, window: str, cwd: str, command: str | None = None) -> TmuxResult:
    args = ["new-window", "-t", session, "-n", window, "-c", cwd]
    if command:
        args.append(command)
    return _run(args)


def split_window(target: str, cwd: str, command: str | None = None) -> TmuxResult:
    args = ["split-window", "-t", target, "-c", cwd]
    if command:
        args.append(command)
    return _run(args)


def split_window_with_id(
    target: str,
    cwd: str,
    command: str | None = None,
    *,
    vertical: bool = False,
    size_percent: int | None = None,
) -> tuple[bool, str]:
    """Split a pane and return the new pane's unique id (e.g. `%23`).

    `vertical=True` splits top/bottom (tmux `-v`); `False` splits
    side-by-side (tmux `-h`). `size_percent` (1–99) controls what
    fraction of the target pane the new pane takes — necessary when
    building grids with equal-sized panes, since tmux's default 50/50
    split would leave uneven widths when splitting the same column
    repeatedly.

    The returned id can be used as a target for subsequent splits so
    callers can build a specific layout by hand instead of relying on
    `select-layout tiled`.
    """
    args = ["split-window", "-t", target, "-c", cwd]
    args.append("-v" if vertical else "-h")
    if size_percent is not None:
        args += ["-l", f"{size_percent}%"]
    args += ["-P", "-F", "#{pane_id}"]
    if command:
        args.append(command)
    r = _run(args)
    if not r.ok:
        return False, ""
    return True, r.stdout.strip()


def select_layout(target: str, layout: str = "tiled") -> TmuxResult:
    return _run(["select-layout", "-t", target, layout])


def select_pane(target: str) -> TmuxResult:
    """Focus a specific pane (e.g. `central:projects.0`)."""
    return _run(["select-pane", "-t", target])


def select_window(target: str) -> TmuxResult:
    """Focus a specific window (e.g. `central:projects`)."""
    return _run(["select-window", "-t", target])


def set_pane_title(target: str, title: str) -> TmuxResult:
    """Give a pane a display title (shown on the pane border when
    `pane-border-status` is enabled)."""
    return _run(["select-pane", "-t", target, "-T", title])


def set_pane_style(target: str, style: str) -> TmuxResult:
    """Apply a style to a specific pane (tmux 3.0+).

    Example: `fg=yellow,bold` or `bg=colour236`. Unlike `pane-active-border-style`,
    this attaches directly to one pane and survives focus changes.
    """
    return _run(["select-pane", "-t", target, "-P", style])


def set_window_option(target: str, name: str, value: str) -> TmuxResult:
    """Set a per-window option (equivalent of `set-window-option -t`)."""
    return _run(["set-window-option", "-t", target, name, value])


def kill_session(name: str) -> TmuxResult:
    return _run(["kill-session", "-t", name])


def _shquote(s: str) -> str:
    if not s or any(c in s for c in " \t\n\"'\\$`"):
        escaped = s.replace("'", "'\\''")
        return f"'{escaped}'"
    return s
