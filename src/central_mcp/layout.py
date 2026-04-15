"""Optional tmux observation layer.

`central-mcp up` creates a single tmux session named `central` with one
window `projects` that contains one interactive pane per registered
project. Each pane runs the adapter's `launch` command wrapped in
`sh -c '<cmd>; exec $SHELL'` so the pane stays alive if the agent
exits. No hub window, no log tail split, no pipe-pane logging —
everything the MCP dispatch path needs lives in `server.py` and talks
directly to subprocesses, independent of whatever tmux is (or isn't)
doing.

Users `tmux attach -t central` and cycle panes with `Ctrl+b n/p` or
`Ctrl+b <digit>` to peek at each agent. `central-mcp down` tears the
whole session back down.
"""

from __future__ import annotations

from central_mcp import tmux
from central_mcp.adapters import get_adapter
from central_mcp.registry import Project, load_registry

SESSION = "central"
WINDOW = "projects"


def _pane_command(p: Project) -> str | None:
    """Shell command to exec in the pane, wrapped to survive agent exit."""
    launch = get_adapter(p.agent).launch_command()
    if not launch:
        return None
    return f"sh -c '{launch}; exec $SHELL'"


def ensure_session() -> tuple[bool, list[str]]:
    """Idempotently create the observation session if it doesn't exist."""
    messages: list[str] = []
    if tmux.has_session(SESSION):
        messages.append(f"session '{SESSION}' already exists — leaving as-is")
        return False, messages

    projects = load_registry()
    if not projects:
        messages.append("registry.yaml has no projects — creating empty session")
        r = tmux.new_session(SESSION, WINDOW, ".")
        if not r.ok:
            messages.append(f"new-session failed: {r.stderr.strip()}")
            return False, messages
        return True, messages

    first, *rest = projects
    r = tmux.new_session(SESSION, WINDOW, first.path, command=_pane_command(first))
    if not r.ok:
        messages.append(f"new-session failed: {r.stderr.strip()}")
        return False, messages
    messages.append(f"pane 0 -> {first.name} ({first.path})")

    target = f"{SESSION}:{WINDOW}"
    for i, p in enumerate(rest, start=1):
        r = tmux.split_window(target, p.path, command=_pane_command(p))
        if not r.ok:
            messages.append(f"split-window for {p.name} failed: {r.stderr.strip()}")
            continue
        messages.append(f"pane {i} -> {p.name} ({p.path})")

    if rest:
        tmux.select_layout(target, "tiled")

    messages.append(f"created '{SESSION}' — attach with: tmux attach -t {SESSION}")
    return True, messages


def kill_all() -> tuple[bool, str]:
    """Kill the central session if it exists. Returns (killed, message)."""
    if not tmux.has_session(SESSION):
        return False, f"no session named '{SESSION}'"
    r = tmux.kill_session(SESSION)
    if not r.ok:
        return False, f"kill-session failed: {r.stderr.strip()}"
    return True, f"killed session '{SESSION}'"
