"""Textual-based TUI shell for central-mcp.

Phase 0 (0.12.0) — claude-only experimental TUI: `cmcp tui --experimental`.
Hosts the orchestrator agent inside a managed PTY, surrounds it with our
own chrome (token HUD, active dispatches, recent completions), and reacts
to dispatch completion *immediately* by polling `dispatches.db` directly
instead of waiting on `notifications/resources/updated` from the MCP
client.

Importing this package is cheap and never requires the optional `[tui]`
extras (textual + pyte). The actual app lives in `central_mcp.tui.app`,
which imports textual at module load time — the CLI translates that
ImportError into an actionable `pip install 'central-mcp[tui]'` hint.
"""
from __future__ import annotations
