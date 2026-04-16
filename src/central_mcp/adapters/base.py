"""Per-agent adapters.

An `Adapter` describes how to talk to a coding-agent CLI in two modes:

- `launch` — the argv to spawn when a human wants an interactive session
  (used by `central-mcp up` to populate each project's tmux pane).
- `exec_argv(prompt, resume=True)` — a one-shot non-interactive argv
  that writes the response to stdout and exits. This is what the
  `dispatch_query` MCP tool invokes for every dispatch, so the
  orchestrator can collect the full response as the subprocess's
  standard output rather than scraping pane bytes.

Adapters that have no non-interactive mode return `None` from
`exec_argv` — the caller surfaces a clear error instead of silently
doing nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass
class Adapter:
    name: str
    launch: Sequence[str] = ()     # interactive-mode argv for tmux panes
    has_exec: bool = False         # whether exec_argv returns non-None

    def launch_command(self) -> str:
        """Shell-joined interactive launch command for tmux panes.

        Empty string means "this adapter has no launch command" — used by
        the `shell` adapter so the pane just shows a plain shell.
        """
        return " ".join(self.launch)

    def exec_argv(self, prompt: str, *, resume: bool = True, bypass: bool = False) -> list[str] | None:
        """Return argv for a one-shot non-interactive invocation.

        Override in subclasses. Return None if this adapter does not
        support non-interactive dispatch. When bypass=True, append the
        agent's permission-skip flag if it has one.
        """
        return None


class _Claude(Adapter):
    def exec_argv(self, prompt: str, *, resume: bool = True, bypass: bool = False) -> list[str] | None:
        argv = ["claude", "-p", prompt]
        if resume:
            argv.append("--continue")
        if bypass:
            argv.append("--dangerously-skip-permissions")
        return argv


class _Codex(Adapter):
    def exec_argv(self, prompt: str, *, resume: bool = True, bypass: bool = False) -> list[str] | None:
        argv = ["codex", "exec", prompt]
        if bypass:
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        return argv


class _Gemini(Adapter):
    def exec_argv(self, prompt: str, *, resume: bool = True, bypass: bool = False) -> list[str] | None:
        argv = ["gemini", "-p", prompt]
        if bypass:
            argv.append("--yolo")
        return argv


class _Droid(Adapter):
    def exec_argv(self, prompt: str, *, resume: bool = True, bypass: bool = False) -> list[str] | None:
        argv = ["droid", "exec", prompt]
        if resume:
            argv.extend(["-r"])  # resume last session
        if bypass:
            argv.append("--skip-permissions-unsafe")
        return argv


_ADAPTERS: dict[str, Adapter] = {
    "claude": _Claude("claude", launch=("claude",), has_exec=True),
    "codex": _Codex("codex", launch=("codex",), has_exec=True),
    "gemini": _Gemini("gemini", launch=("gemini",), has_exec=True),
    "droid": _Droid("droid", launch=("droid",), has_exec=True),
    "shell": Adapter("shell", launch=(), has_exec=False),
}

VALID_AGENTS = {"claude", "codex", "gemini", "droid", "shell"}


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS.get(name, _ADAPTERS["shell"])
