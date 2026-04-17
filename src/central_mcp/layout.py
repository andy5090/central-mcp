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


def _pane_command(p: Project) -> str:
    """Project pane command — stream this project's dispatch events."""
    return _wrap(f"central-mcp watch {p.name}")


def ensure_session(
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
) -> tuple[bool, list[str]]:
    """Idempotently create the observation session if it doesn't exist.

    With `orchestrator` given it becomes pane 0 of the first window,
    and that window's name gets a `-hub` suffix so it's instantly
    distinguishable from overflow windows. The full plan (orchestrator
    + projects) is chunked into windows of at most `panes_per_window`
    panes so tmux never runs out of pane space for any registry size.

    Project panes run `central-mcp watch <project>` so users see
    dispatch activity live in each pane.
    """
    if panes_per_window < 1:
        raise ValueError(f"panes_per_window must be >= 1, got {panes_per_window}")
    messages: list[str] = []
    if tmux.has_session(SESSION):
        messages.append(f"session '{SESSION}' already exists — leaving as-is")
        return False, messages

    projects = load_registry()
    has_orchestrator = orchestrator is not None

    # Each plan entry: (title_for_border, cwd, wrapped_cmd, is_orchestrator)
    plan: list[tuple[str, str, str | None, bool]] = []
    if orchestrator is not None:
        plan.append((
            "Central MCP Orchestrator",
            orchestrator.cwd,
            _wrap(orchestrator.command),
            True,
        ))
    for p in projects:
        plan.append((p.name, p.path, _pane_command(p), False))

    if not plan:
        messages.append("registry.yaml has no projects and no orchestrator — creating empty session")
        r = tmux.new_session(SESSION, window_name(0), ".")
        if not r.ok:
            messages.append(f"new-session failed: {r.stderr.strip()}")
            return False, messages
        return True, messages

    # Chunk into windows.
    # - Hub window (contains orchestrator) holds `panes_per_window - 1`
    #   panes: orchestrator visually takes two cells via main-vertical,
    #   so the window still feels like `panes_per_window` cells worth.
    # - Overflow windows hold the full `panes_per_window` project panes.
    chunks: list[list[tuple[str, str, str | None, bool]]] = []
    first_size = panes_per_window - 1 if (has_orchestrator and panes_per_window >= 2) else panes_per_window
    if first_size < 1:
        first_size = 1
    chunks.append(plan[:first_size])
    remaining = plan[first_size:]
    for i in range(0, len(remaining), panes_per_window):
        chunks.append(remaining[i:i + panes_per_window])

    for win_idx, chunk in enumerate(chunks):
        wname = window_name(win_idx, has_orchestrator=has_orchestrator)
        target = f"{SESSION}:{wname}"
        first_title, first_cwd, first_cmd, first_is_orch = chunk[0]

        if win_idx == 0:
            r = tmux.new_session(SESSION, wname, first_cwd, command=first_cmd)
            op = "new-session"
        else:
            r = tmux.new_window(SESSION, wname, first_cwd, command=first_cmd)
            op = "new-window"
        if not r.ok:
            messages.append(f"{op} for {wname} failed: {r.stderr.strip()}")
            continue
        messages.append(f"{wname} pane 0 -> {first_title} ({first_cwd})")

        # Pane border titles make each pane self-identify. Apply to every
        # pane we create, orchestrator included. (set-option scope is
        # per-window so this line suffices to turn titles on.)
        tmux.set_window_option(target, "pane-border-status", "top")
        # Highlight the orchestrator pane's title in bold yellow via a
        # conditional border format. Changing pane-border-format (title
        # text) does NOT fight with pane-active-border-style (border
        # characters), so tmux's own active-pane indicator still works.
        if first_is_orch:
            tmux.set_window_option(
                target,
                "pane-border-format",
                "#[fg=#{?#{==:#{pane_index},0},yellow,default},bold]#{pane_title}",
            )
        tmux.set_pane_title(f"{target}.0", first_title)

        for i, (title, cwd, cmd, is_orch) in enumerate(chunk[1:], start=1):
            r = tmux.split_window(target, cwd, command=cmd)
            if not r.ok:
                messages.append(f"split-window for {title} failed: {r.stderr.strip()}")
                continue
            messages.append(f"{wname} pane {i} -> {title} ({cwd})")
            tmux.set_pane_title(f"{target}.{i}", title)
            # Re-tile after every split so tmux redistributes space.
            tmux.select_layout(target, "tiled")

        # Hub window uses main-vertical with a 50% split so the
        # orchestrator gets the left half and projects stack on the
        # right. Overflow windows stay tiled so equal-size project
        # panes read well.
        if win_idx == 0 and has_orchestrator:
            tmux.set_window_option(target, "main-pane-width", "50%")
            tmux.select_layout(target, "main-vertical")

    # Focus the first window/pane so attaching users land on pane 0
    # (orchestrator when present) rather than the last-split pane.
    first_wname = window_name(0, has_orchestrator=has_orchestrator)
    tmux.select_window(f"{SESSION}:{first_wname}")
    tmux.select_pane(f"{SESSION}:{first_wname}.0")

    messages.append(f"created '{SESSION}' — attach with: central-mcp tmux")
    return True, messages


def kill_all() -> tuple[bool, str]:
    """Kill the central session if it exists. Returns (killed, message)."""
    if not tmux.has_session(SESSION):
        return False, f"no session named '{SESSION}'"
    r = tmux.kill_session(SESSION)
    if not r.ok:
        return False, f"kill-session failed: {r.stderr.strip()}"
    return True, f"killed session '{SESSION}'"
