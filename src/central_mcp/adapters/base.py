from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Adapter:
    """Describes how to start a particular agent CLI in a tmux pane."""

    name: str
    launch: str           # fresh-start shell command
    resume: str = ""      # resume-last-session command; empty = not supported

    def launch_command(self, *, resume: bool = False) -> str:
        if resume and self.resume:
            return self.resume
        return self.launch


_ADAPTERS: dict[str, Adapter] = {
    "claude": Adapter("claude", "claude", resume="claude -c"),
    "codex": Adapter("codex", "codex", resume="codex resume --last"),
    "gemini": Adapter("gemini", "gemini"),
    "cursor": Adapter("cursor", "cursor-agent"),
    "shell": Adapter("shell", ""),
}


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS.get(name, _ADAPTERS["shell"])


def _claude_has_history(cwd: str) -> bool:
    slug = re.sub(r"[^A-Za-z0-9]", "-", cwd)
    d = Path.home() / ".claude" / "projects" / slug
    if not d.exists():
        return False
    try:
        return any(d.glob("*.jsonl"))
    except OSError:
        return False


_HISTORY_CHECKS: dict[str, Callable[[str], bool]] = {
    "claude": _claude_has_history,
}


def has_history(agent: str, cwd: str) -> bool:
    """True if there is prior session data for (agent, cwd) that the resume
    command could pick up. Used by lazy-boot to prefer `resume` over `launch`.
    """
    check = _HISTORY_CHECKS.get(agent)
    return bool(check and check(cwd))
