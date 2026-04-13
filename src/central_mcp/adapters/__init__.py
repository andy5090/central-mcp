"""Agent adapters — one per coding-agent CLI.

Each adapter describes how to launch a given agent in a tmux pane. The goal
is to keep the rest of central-mcp ignorant of per-agent quirks: everything
else deals with `Project` and `Adapter.launch_command()`.
"""

from central_mcp.adapters.base import Adapter, get_adapter

__all__ = ["Adapter", "get_adapter"]
