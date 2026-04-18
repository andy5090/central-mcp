"""Per-agent adapters.

An `Adapter` describes how to talk to a coding-agent CLI in two modes:

- `launch` — the argv to spawn when a human wants an interactive session
  (used by `central-mcp up` to populate each project's tmux pane).
- `exec_argv(prompt, resume=True, permission_mode=...)` — a one-shot
  non-interactive argv that writes the response to stdout and exits.
  This is what the `dispatch` MCP tool invokes for every dispatch, so the
  orchestrator can collect the full response as the subprocess's
  standard output rather than scraping pane bytes.

Adapters that have no non-interactive mode return `None` from
`exec_argv` — the caller surfaces a clear error instead of silently
doing nothing.

`permission_mode` is one of:
  - `"bypass"`      — append the agent's permission-skip flag
                       (claude: --dangerously-skip-permissions,
                        codex: --dangerously-bypass-approvals-and-sandbox,
                        gemini: --yolo, droid: --skip-permissions-unsafe,
                        opencode: --dangerously-skip-permissions)
  - `"auto"`        — claude only: --enable-auto-mode --permission-mode auto
                       (classifier-reviewed). Other agents have no
                       equivalent; only claude emits flags in this mode,
                       others behave as `"restricted"`.
  - `"restricted"`  — no permission-skip flag; agent may fail on
                       approval prompts in `-p` mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


VALID_PERMISSION_MODES = frozenset({"bypass", "auto", "restricted"})


@dataclass
class Adapter:
    name: str
    launch: Sequence[str] = ()     # interactive-mode argv for tmux panes
    has_exec: bool = False         # whether exec_argv returns non-None
    supports_auto: bool = False    # whether this adapter implements `auto`

    def launch_command(self) -> str:
        """Shell-joined interactive launch command for tmux panes.

        Empty string means "this adapter has no launch command" — the
        fallback adapter uses this so a lookup on an unknown name
        degrades to a bare pane rather than crashing.
        """
        return " ".join(self.launch)

    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
    ) -> list[str] | None:
        """Return argv for a one-shot non-interactive invocation.

        Override in subclasses. Return None if this adapter does not
        support non-interactive dispatch.
        """
        return None


class _Claude(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
    ) -> list[str] | None:
        argv = ["claude", "-p", prompt]
        if resume:
            argv.append("--continue")
        if permission_mode == "bypass":
            argv.append("--dangerously-skip-permissions")
        elif permission_mode == "auto":
            argv.extend(["--enable-auto-mode", "--permission-mode", "auto"])
        return argv


class _Codex(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
    ) -> list[str] | None:
        if resume:
            argv = ["codex", "exec", "resume", "--last", prompt]
        else:
            argv = ["codex", "exec", prompt]
        if permission_mode == "bypass":
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        return argv


class _Gemini(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
    ) -> list[str] | None:
        argv = ["gemini", "-p", prompt]
        if resume:
            argv += ["--resume", "latest"]
        if permission_mode == "bypass":
            argv.append("--yolo")
        return argv


class _Droid(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
    ) -> list[str] | None:
        # `droid exec` has no session-resume flag — `-r` is
        # reasoning-effort (takes a value like low/medium/high), not
        # resume, so adding it here was a bug. We ignore `resume`
        # entirely for droid.
        argv = ["droid", "exec", prompt]
        if permission_mode == "bypass":
            argv.append("--skip-permissions-unsafe")
        return argv


class _OpenCode(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
    ) -> list[str] | None:
        argv = ["opencode", "run", prompt]
        if resume:
            argv.append("--continue")
        if permission_mode == "bypass":
            argv.append("--dangerously-skip-permissions")
        return argv


# `amp` was previously supported as a dispatch target but has been
# removed: Amp Free rejects `amp -x` with "Execute mode ... require
# paid credits", making the adapter unusable for the majority of
# potential users.


_ADAPTERS: dict[str, Adapter] = {
    "claude":   _Claude("claude",   launch=("claude",),   has_exec=True, supports_auto=True),
    "codex":    _Codex("codex",     launch=("codex",),    has_exec=True),
    "gemini":   _Gemini("gemini",   launch=("gemini",),   has_exec=True),
    "droid":    _Droid("droid",     launch=("droid",),    has_exec=True),
    "opencode": _OpenCode("opencode", launch=("opencode",), has_exec=True),
}

# Internal fallback for `get_adapter(unknown)` — no launch, no exec.
# Not exposed as a valid agent name; it exists only so callers don't
# have to special-case missing adapters.
_FALLBACK_ADAPTER = Adapter("(unknown)", launch=(), has_exec=False)

VALID_AGENTS = {"claude", "codex", "gemini", "droid", "opencode"}


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS.get(name, _FALLBACK_ADAPTER)
