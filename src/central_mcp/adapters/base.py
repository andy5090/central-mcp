from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Adapter:
    """Describes how to start a particular agent CLI in a tmux pane."""

    name: str
    launch: str  # shell command to run in the pane's cwd

    def launch_command(self) -> str:
        return self.launch


# Built-in adapters. The launch strings are intentionally minimal — no
# autoresume, no model flags. Users override per-project by editing the
# registry (Phase 2 will expose per-project launch overrides).
_ADAPTERS: dict[str, Adapter] = {
    "claude": Adapter("claude", "claude"),
    "codex": Adapter("codex", "codex"),
    "gemini": Adapter("gemini", "gemini"),
    "cursor": Adapter("cursor", "cursor-agent"),
    "shell": Adapter("shell", ""),  # empty = don't launch anything
}


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS.get(name, _ADAPTERS["shell"])
