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
from typing import Sequence


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

    def exec_argv(self, prompt: str, *, resume: bool = True) -> list[str] | None:
        """Return argv for a one-shot non-interactive invocation.

        Override in subclasses. Return None if this adapter does not
        support non-interactive dispatch.
        """
        return None


class _Claude(Adapter):
    def exec_argv(self, prompt: str, *, resume: bool = True) -> list[str] | None:
        argv = ["claude", "-p", prompt]
        if resume:
            # --continue resumes the most recent conversation in the
            # subprocess's working directory, which for us is always the
            # project's own cwd. This keeps multi-turn context implicit
            # without forcing the registry to track a session-id per project.
            argv.append("--continue")
        return argv


class _Codex(Adapter):
    def exec_argv(self, prompt: str, *, resume: bool = True) -> list[str] | None:
        # `codex exec` is codex's one-shot mode. Codex's resume semantics
        # require explicit session IDs and don't compose cleanly with
        # `exec`, so dispatches are stateless for now — each call starts
        # a fresh codex context in the project's cwd.
        return ["codex", "exec", prompt]


class _Gemini(Adapter):
    def exec_argv(self, prompt: str, *, resume: bool = True) -> list[str] | None:
        return ["gemini", "-p", prompt]


_ADAPTERS: dict[str, Adapter] = {
    "claude": _Claude("claude", launch=("claude",), has_exec=True),
    "codex": _Codex("codex", launch=("codex",), has_exec=True),
    "gemini": _Gemini("gemini", launch=("gemini",), has_exec=True),
    "cursor": Adapter("cursor", launch=("cursor-agent",), has_exec=False),
    "shell": Adapter("shell", launch=(), has_exec=False),
}


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS.get(name, _ADAPTERS["shell"])
