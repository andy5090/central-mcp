"""Agent adapters — one per coding-agent CLI.

Each adapter describes both the interactive launch command (for tmux
panes via `central-mcp up`) and the one-shot `exec_argv` used by
`dispatch_query` to collect responses over stdout.
"""

from central_mcp.adapters.base import Adapter, get_adapter

__all__ = ["Adapter", "get_adapter"]
