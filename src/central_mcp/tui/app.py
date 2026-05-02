"""Top-level Textual app for `cmcp tui --experimental`.

Layout (single window, no internal multiplexing — Phase 0):

    ┌──────────────────────────────────────────────────┐
    │ Header                                           │
    ├──────────┬───────────────────────────────────────┤
    │ Sidebar  │ PtyTerminal (claude REPL)             │
    │ - tokens │                                       │
    │ - active │                                       │
    │ - recent │                                       │
    ├──────────┴───────────────────────────────────────┤
    │ Footer                                           │
    └──────────────────────────────────────────────────┘

Importing this module pulls textual + pyte at module load — callers
that need to detect a missing `[tui]` extra should `try: import
central_mcp.tui.app` and translate ImportError into the install hint
via `central_mcp.tui.errors.print_missing_extras`.
"""
from __future__ import annotations

import shutil

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from central_mcp.tui.sidebar import Sidebar
from central_mcp.tui.terminal import PtyTerminal
from central_mcp.tui.watcher import DispatchWatcher


_AGENT_LAUNCH = {
    # Phase 0 ships claude-only. Codex / gemini / opencode arrive in
    # 0.13 / 0.14; their argv lives here so adding them is one-line.
    "claude": ["claude"],
}


class CentralMcpTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    TITLE = "central-mcp · TUI"
    SUB_TITLE = "experimental"

    def __init__(self, agent: str = "claude") -> None:
        super().__init__()
        self.agent = agent
        self._sidebar: Sidebar | None = None
        self._terminal: PtyTerminal | None = None
        self._watcher: DispatchWatcher | None = None

    def compose(self) -> ComposeResult:
        argv = _AGENT_LAUNCH.get(self.agent, [self.agent])
        self._sidebar = Sidebar()
        self._terminal = PtyTerminal(command=argv)
        # `icon="MENU"` overrides the default `⭘` glyph that renders as
        # a bare "o" in many monospace fonts and gives no visual hint
        # that clicking opens the command palette.
        yield Header(icon="MENU")
        with Horizontal(id="body"):
            yield self._sidebar
            yield self._terminal
        yield Footer()

    def on_mount(self) -> None:
        # Sidebar references resolve after compose; safe to wire now.
        if self._sidebar is not None:
            self._watcher = DispatchWatcher(self, self._sidebar)
            self._watcher.start()

    def on_unmount(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()


def run_tui(agent: str = "claude") -> int:
    """Launch the TUI. Returns process exit code."""
    if agent not in _AGENT_LAUNCH:
        # Defensive: CLI already filters, but a programmatic caller
        # could land here with an unsupported agent.
        import sys
        sys.stderr.write(
            f"error: tui agent {agent!r} not supported in 0.12.x.\n"
            "       supported: " + ", ".join(_AGENT_LAUNCH) + "\n"
        )
        return 2
    if shutil.which(agent) is None:
        import sys
        sys.stderr.write(
            f"error: {agent!r} CLI not found on PATH. Install it first, "
            "or pass --agent <name> when more agents are supported.\n"
        )
        return 2
    app = CentralMcpTUI(agent=agent)
    app.run()
    return 0
