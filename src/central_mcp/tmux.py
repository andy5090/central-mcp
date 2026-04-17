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


def select_layout(target: str, layout: str = "tiled") -> TmuxResult:
    return _run(["select-layout", "-t", target, layout])


def select_pane(target: str) -> TmuxResult:
    """Focus a specific pane (e.g. `central:projects.0`)."""
    return _run(["select-pane", "-t", target])


def select_window(target: str) -> TmuxResult:
    """Focus a specific window (e.g. `central:projects`)."""
    return _run(["select-window", "-t", target])


def kill_session(name: str) -> TmuxResult:
    return _run(["kill-session", "-t", name])


def _shquote(s: str) -> str:
    if not s or any(c in s for c in " \t\n\"'\\$`"):
        escaped = s.replace("'", "'\\''")
        return f"'{escaped}'"
    return s
