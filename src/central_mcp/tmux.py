from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


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


def pane_exists(target: str) -> bool:
    """True if `target` resolves to an existing pane.

    tmux is lenient about the `.N` suffix: asking for a non-existent pane
    index silently falls back to the window's active pane, so a naive
    display-message check would return True for any window that exists.
    When `target` contains an explicit pane index we cross-check it against
    list-panes output and require an exact match.
    """
    if ":" in target and "." in target.rsplit(":", 1)[-1]:
        session_window, idx_str = target.rsplit(".", 1)
        try:
            want = int(idx_str)
        except ValueError:
            return False
        r = _run(["list-panes", "-t", session_window, "-F", "#{pane_index}"])
        if not r.ok:
            return False
        indices = {int(x) for x in r.stdout.split() if x.strip().isdigit()}
        return want in indices
    return _run(["display-message", "-p", "-t", target, "#{pane_id}"]).ok


def pane_in_copy_mode(target: str) -> bool:
    r = _run(["display-message", "-p", "-t", target, "#{pane_in_mode}"])
    return r.ok and r.stdout.strip() == "1"


def pane_current_command(target: str) -> str:
    r = _run(["display-message", "-p", "-t", target, "#{pane_current_command}"])
    return r.stdout.strip() if r.ok else ""


def send_keys(target: str, text: str, enter: bool = True) -> TmuxResult:
    result = _run(["send-keys", "-t", target, "-l", text])
    if not result.ok:
        return result
    if enter:
        return _run(["send-keys", "-t", target, "Enter"])
    return result


def capture_pane(target: str, lines: int = 200) -> TmuxResult:
    return _run(["capture-pane", "-p", "-t", target, "-S", f"-{lines}"])


def new_session(name: str, window: str, cwd: str) -> TmuxResult:
    return _run(["new-session", "-d", "-s", name, "-n", window, "-c", cwd])


def new_window(session: str, window: str, cwd: str) -> TmuxResult:
    return _run(["new-window", "-t", session, "-n", window, "-c", cwd])


def split_window(target: str, cwd: str) -> TmuxResult:
    return _run(["split-window", "-t", target, "-c", cwd])


def select_layout(target: str, layout: str = "tiled") -> TmuxResult:
    return _run(["select-layout", "-t", target, layout])


def pipe_pane_to_file(target: str, log_path: Path) -> TmuxResult:
    """Start piping every byte written to `target` into `log_path` (appended).

    Re-invoking with the same target replaces the previous pipe (tmux behavior).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # -o = only-open (toggle off if already piping with same command)
    # Use a shell fragment so tmux can expand the redirection.
    shell_cmd = f"cat >> {_shquote(str(log_path))}"
    return _run(["pipe-pane", "-t", target, shell_cmd])


def _shquote(s: str) -> str:
    if not s or any(c in s for c in " \t\n\"'\\$`"):
        escaped = s.replace("'", "'\\''")
        return f"'{escaped}'"
    return s
