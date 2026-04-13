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


def pane_exists(target: str) -> bool:
    return _run(["display-message", "-p", "-t", target, "#{pane_id}"]).ok


def send_keys(target: str, text: str, enter: bool = True) -> TmuxResult:
    # Send as a literal single argument so spaces/newlines survive.
    result = _run(["send-keys", "-t", target, "-l", text])
    if not result.ok:
        return result
    if enter:
        return _run(["send-keys", "-t", target, "Enter"])
    return result


def capture_pane(target: str, lines: int = 200) -> TmuxResult:
    # -p = print to stdout; -S -N = start N lines from the end of scrollback.
    return _run(["capture-pane", "-p", "-t", target, "-S", f"-{lines}"])
