"""Optional tmux observation layer.

`central-mcp up` creates a single tmux session named `central`.
Windows are named `cmcp-1`, `cmcp-2`, `cmcp-3`, … with the first
window picking up a `-hub` suffix (`cmcp-1-hub`) when it holds the
orchestrator pane. Each window holds up to `DEFAULT_PANES_PER_WINDOW`
(4) panes — overflow spills into the next window.

Each pane runs its launch command wrapped in `sh -c '<cmd>; exec
$SHELL'` so the pane stays alive if the process exits. No hub window,
no log tail split, no pipe-pane logging — everything the MCP dispatch
path needs lives in `server.py` and talks directly to subprocesses,
independent of whatever tmux is (or isn't) doing.

Users `tmux attach -t central` and cycle panes with `Ctrl+b n/p` or
`Ctrl+b <digit>`. Switch windows with `Ctrl+b <digit>` at the window
level or `Ctrl+b w`. `central-mcp down` tears the whole session back
down.
"""

from __future__ import annotations

from dataclasses import dataclass

from central_mcp import tmux
from central_mcp.adapters import get_adapter
from central_mcp.registry import Project, load_registry

SESSION = "central"
WINDOW_BASE = "cmcp"
HUB_SUFFIX = "-hub"
DEFAULT_PANES_PER_WINDOW = 4


def window_name(window_index: int = 0, *, has_orchestrator: bool = False) -> str:
    """Canonical window name for index N.

    The first window (index 0) carries a `-hub` suffix when it contains
    the orchestrator pane, so users can tell at a glance which window
    holds the hub: `cmcp-1-hub` vs `cmcp-2`, `cmcp-3`, …
    """
    base = f"{WINDOW_BASE}-{window_index + 1}"
    if window_index == 0 and has_orchestrator:
        return base + HUB_SUFFIX
    return base


@dataclass
class OrchestratorPane:
    """Describes the orchestrator pane to prepend at index 0."""
    command: str  # e.g. "claude" or "claude --dangerously-skip-permissions"
    cwd: str      # launch directory (usually central-mcp home)
    label: str    # human-readable name for status messages


def _wrap(launch: str) -> str:
    """Wrap a launch command so the pane survives after the process exits."""
    return f"sh -c '{launch}; exec $SHELL'"


def _watch_command(project_name: str) -> str:
    """Default pane command — stream this project's dispatch events."""
    return _wrap(f"central-mcp watch {project_name}")


def _interactive_pane_command(p: Project) -> str | None:
    """Legacy pane command — run the agent's own interactive CLI."""
    launch = get_adapter(p.agent).launch_command()
    if not launch:
        return None
    return _wrap(launch)


def _pane_command(p: Project, interactive: bool = False) -> str | None:
    if interactive:
        return _interactive_pane_command(p)
    return _watch_command(p.name)


def ensure_session(
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
    interactive_panes: bool = False,
) -> tuple[bool, list[str]]:
    """Idempotently create the observation session if it doesn't exist.

    With `orchestrator` given it becomes pane 0 of the first window,
    and that window's name gets a `-hub` suffix so it's instantly
    distinguishable from overflow windows. The full plan (orchestrator
    + projects) is chunked into windows of at most `panes_per_window`
    panes so tmux never runs out of pane space for any registry size.

    When `interactive_panes` is False (default), project panes run
    `central-mcp watch <project>` so users see dispatch activity live.
    Set it to True to restore the legacy behavior of running each
    agent's interactive CLI in its pane.
    """
    if panes_per_window < 1:
        raise ValueError(f"panes_per_window must be >= 1, got {panes_per_window}")
    messages: list[str] = []
    if tmux.has_session(SESSION):
        messages.append(f"session '{SESSION}' already exists — leaving as-is")
        return False, messages

    projects = load_registry()
    has_orchestrator = orchestrator is not None

    plan: list[tuple[str, str, str | None]] = []
    if orchestrator is not None:
        plan.append((f"orchestrator ({orchestrator.label})",
                     orchestrator.cwd,
                     _wrap(orchestrator.command)))
    for p in projects:
        plan.append((p.name, p.path, _pane_command(p, interactive=interactive_panes)))

    if not plan:
        messages.append("registry.yaml has no projects and no orchestrator — creating empty session")
        r = tmux.new_session(SESSION, window_name(0), ".")
        if not r.ok:
            messages.append(f"new-session failed: {r.stderr.strip()}")
            return False, messages
        return True, messages

    # Chunk into windows of at most panes_per_window.
    chunks = [plan[i:i + panes_per_window] for i in range(0, len(plan), panes_per_window)]

    for win_idx, chunk in enumerate(chunks):
        wname = window_name(win_idx, has_orchestrator=has_orchestrator)
        target = f"{SESSION}:{wname}"
        first_label, first_cwd, first_cmd = chunk[0]

        if win_idx == 0:
            r = tmux.new_session(SESSION, wname, first_cwd, command=first_cmd)
            op = "new-session"
        else:
            r = tmux.new_window(SESSION, wname, first_cwd, command=first_cmd)
            op = "new-window"
        if not r.ok:
            messages.append(f"{op} for {wname} failed: {r.stderr.strip()}")
            continue
        messages.append(f"{wname} pane 0 -> {first_label} ({first_cwd})")

        for i, (label, cwd, cmd) in enumerate(chunk[1:], start=1):
            r = tmux.split_window(target, cwd, command=cmd)
            if not r.ok:
                messages.append(f"split-window for {label} failed: {r.stderr.strip()}")
                continue
            messages.append(f"{wname} pane {i} -> {label} ({cwd})")
            # Re-tile after every split so tmux redistributes space.
            tmux.select_layout(target, "tiled")

    # Focus the first window/pane so attaching users land on pane 0
    # (orchestrator when present) rather than the last-split pane.
    first_wname = window_name(0, has_orchestrator=has_orchestrator)
    tmux.select_window(f"{SESSION}:{first_wname}")
    tmux.select_pane(f"{SESSION}:{first_wname}.0")

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
