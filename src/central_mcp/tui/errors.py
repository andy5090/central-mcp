"""Actionable error helpers for `cmcp tui`.

Exit code 2 (usage error) for both opt-out paths so wrappers / shells can
distinguish them from successful runs and from runtime crashes.
"""
from __future__ import annotations

import sys


EXPERIMENTAL_HINT = (
    "error: `cmcp tui` is experimental and not API-stable yet — opt in with\n"
    "       cmcp tui --experimental\n"
    "       (the flag becomes a no-op once the TUI graduates to 1.0.)\n"
)


MISSING_EXTRAS_HINT = (
    "error: TUI dependencies (textual / pyte) are not installed.\n"
    "       install with one of:\n"
    "         pip install 'central-mcp[tui]'\n"
    "         uv tool install --reinstall 'central-mcp[tui]'\n"
    "       central-mcp itself runs without them — the [tui] extra brings\n"
    "       in textual (chrome) and pyte (terminal emulator) only when you\n"
    "       want the embedded TUI.\n"
)


def print_experimental_required() -> int:
    sys.stderr.write(EXPERIMENTAL_HINT)
    return 2


def print_missing_extras(detail: str = "") -> int:
    sys.stderr.write(MISSING_EXTRAS_HINT)
    if detail:
        sys.stderr.write(f"       underlying error: {detail}\n")
    return 2
