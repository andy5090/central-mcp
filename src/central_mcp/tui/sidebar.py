"""Sidebar panes — token HUD + active dispatches + recent completions.

Wired to a live watcher (`tui.watcher.DispatchWatcher`) on
`~/.central-mcp/dispatches.db`. The watcher pushes (active, recent)
tuples and refreshed token-summary text into the widgets here; this
module is purely view code so it stays trivially testable.
"""
from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


_STATUS_MARK = {
    "complete":  "[green]✓[/]",
    "error":     "[red]✗[/]",
    "cancelled": "[yellow]⊘[/]",
    "timeout":   "[yellow]⏱[/]",
}


class TokenHud(Static):
    """Renders the markdown summary from `tokens_db.aggregate(...)`.

    The watcher feeds in plain text (the fenced ```text``` body) so block
    bars (`█`/`░`) and emoji color markers stay column-aligned.
    """

    DEFAULT_CSS = """
    TokenHud { height: auto; padding: 0 1; color: $text; }
    """

    def __init__(self) -> None:
        super().__init__(Text.from_markup("Tokens · loading…"))


class DispatchList(Static):
    """Two-section block: ACTIVE (running) + RECENT (last terminal states)."""

    DEFAULT_CSS = """
    DispatchList { height: auto; padding: 1; color: $text; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._active: list[dict[str, Any]] = []
        self._recent: list[dict[str, Any]] = []
        self.update(Text.from_markup(self._build_text()))

    def update_dispatches(
        self,
        active: list[dict[str, Any]] | None,
        recent: list[dict[str, Any]] | None,
    ) -> None:
        self._active = list(active or [])
        self._recent = list(recent or [])
        self.update(Text.from_markup(self._build_text()))

    def _build_text(self) -> str:
        lines: list[str] = ["[b]Active[/b]"]
        if not self._active:
            lines.append("  [dim](none)[/]")
        else:
            for d in self._active[:8]:
                lines.append(_format_dispatch_line(d, marker="[cyan]●[/]"))
        lines.append("")
        lines.append("[b]Recent[/b]")
        if not self._recent:
            lines.append("  [dim](none)[/]")
        else:
            for d in self._recent[:5]:
                marker = _STATUS_MARK.get(d.get("status") or "", "·")
                lines.append(_format_dispatch_line(d, marker=marker))
        return "\n".join(lines)


def _format_dispatch_line(entry: dict[str, Any], *, marker: str) -> str:
    project = entry.get("project") or "?"
    agent = entry.get("agent") or "?"
    return f"  {marker} {project} [dim]· {agent}[/]"


class Sidebar(Vertical):
    """Container that stacks the token HUD and dispatch list."""

    DEFAULT_CSS = """
    Sidebar {
        width: 40;
        background: $panel;
        border-right: solid $accent;
        padding-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.token_hud = TokenHud()
        self.dispatch_list = DispatchList()

    def compose(self) -> ComposeResult:
        yield self.token_hud
        yield self.dispatch_list
