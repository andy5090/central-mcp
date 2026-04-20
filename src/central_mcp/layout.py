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


def _fill_column(
    wname: str,
    col_anchor: str,
    col_plans: list[tuple[str, str, str | None, bool]],
    target_rows: int,
    messages: list[str],
) -> None:
    """Stack `target_rows` panes top-to-bottom in a single column.

    Mirrors `_fill_row` but with `-v` splits instead of `-h`. Used for
    narrow-terminal layouts where horizontal splitting would put each
    pane below the readable-width floor.
    """
    if not col_plans or target_rows <= 1:
        return
    bottommost = col_anchor
    for i, (title, cwd, cmd, _) in enumerate(col_plans):
        remaining_after = target_rows - 1 - i
        parent_holds = target_rows - i
        size = max(1, min(99, (remaining_after * 100) // parent_holds))
        ok, new_id = tmux.split_window_with_id(
            bottommost, cwd, cmd, vertical=True, size_percent=size,
        )
        if not ok:
            messages.append(f"split-window for {title} failed")
            continue
        bottommost = new_id
        tmux.set_pane_title(new_id, title)
        messages.append(f"{wname} -> {title} ({cwd})")


def _fill_row(
    wname: str,
    row_anchor: str,
    row_plans: list[tuple[str, str, str | None, bool]],
    target_cols: int,
    messages: list[str],
) -> None:
    """Extend `row_anchor` into a horizontal row of `target_cols` panes.

    The row starts with one existing pane (the anchor). Each additional
    pane is added via a horizontal split of the current rightmost pane
    with a size percentage tuned so all `target_cols` panes end up with
    equal widths. For the i-th additional split (0-indexed) out of
    `target_cols - 1` total splits, the new pane takes
    `(target_cols - 1 - i) / (target_cols - i)` of the split target;
    plugging i=0 into k=4 gives 75% (leaves anchor at 25%, new at 75%),
    i=1 gives 67%, i=2 gives 50%, producing [25%,25%,25%,25%] overall.
    """
    if not row_plans or target_cols <= 1:
        return
    rightmost = row_anchor
    for i, (title, cwd, cmd, _) in enumerate(row_plans):
        remaining_after = target_cols - 1 - i
        parent_holds = target_cols - i
        size = max(1, min(99, (remaining_after * 100) // parent_holds))
        ok, new_id = tmux.split_window_with_id(
            rightmost, cwd, cmd, vertical=False, size_percent=size,
        )
        if not ok:
            messages.append(f"split-window for {title} failed")
            continue
        rightmost = new_id
        tmux.set_pane_title(new_id, title)
        messages.append(f"{wname} -> {title} ({cwd})")


def _fill_orch_column_grid(
    target: str,
    wname: str,
    anchor_id: str,
    plans: list[tuple[str, str, str | None, bool]],
    messages: list[str],
) -> None:
    """Layout variant: anchor = orchestrator, taking a full-height
    left column sized to match one project column. Right area holds
    the project panes in a 2-row (or computed-row) grid.

    For `k` project cols in the top project row, the orchestrator
    column is sized to 1/(k+1) of the window width, matching one
    project column. `orch + 1 project` reproduces a 50/50 split.
    """
    from central_mcp.grid import pick_rows

    project_plans = plans
    if not project_plans:
        return
    project_rows = pick_rows(len(project_plans))
    top_cols = (len(project_plans) + project_rows - 1) // max(project_rows, 1)
    # Orchestrator occupies 1 of (top_cols + 1) total columns.
    right_size = max(1, min(99, top_cols * 100 // (top_cols + 1)))

    first_proj = project_plans[0]
    ok, right_anchor = tmux.split_window_with_id(
        anchor_id, first_proj[1], first_proj[2],
        vertical=False, size_percent=right_size,
    )
    if not ok:
        messages.append(f"split-window for {first_proj[0]} failed")
        return
    tmux.set_pane_title(right_anchor, first_proj[0])
    messages.append(f"{wname} -> {first_proj[0]} ({first_proj[1]})")
    # Recurse into the right area with the normal grid layout.
    _fill_grid(
        target, wname, right_anchor, project_plans[1:], project_rows, messages,
    )


def _fill_grid(
    target: str,
    wname: str,
    anchor_id: str,
    plans: list[tuple[str, str, str | None, bool]],
    rows: int,
    messages: list[str],
) -> None:
    """Extend an existing anchor pane into an `rows` × dynamic-cols grid.

    The anchor occupies the full target area. Plans are distributed
    top-row-heavy: for total panes N = 1 + len(plans), the top row
    takes `ceil(N / rows)` and subsequent rows take proportional
    shares. Equal-size panes are achieved by size-percentage math on
    each split rather than by calling `select-layout` (which would
    undo the structure). Split failures append to `messages`; a
    partially built grid is still usable.
    """
    from central_mcp.grid import row_sizes

    total = 1 + len(plans)
    if total <= 1:
        return

    # When the caller asks for rows == total, build a pure vertical
    # stack (1 col × total rows) — used for narrow terminals where
    # horizontal splitting would violate the width floor.
    if rows >= total and rows > 1:
        _fill_column(wname, anchor_id, plans, target_rows=total, messages=messages)
        return
    # Force single-row layout when caller asks for rows <= 1 or every
    # pane fits in a single row already.
    if rows <= 1 or total <= rows:
        # Single row, `total` equal-width cols.
        _fill_row(wname, anchor_id, plans, target_cols=total, messages=messages)
        return

    sizes = row_sizes(total, rows)  # e.g. total=10, rows=2 → [5, 5]
    # We'll hold a list of (row_anchor_id, cols_in_this_row) and fill each
    # row with horizontal splits after we've created its anchor pane.
    row_anchors: list[str] = [anchor_id]
    plan_idx = 0

    # Step 1: create one anchor pane per additional row via vertical
    # splits. Each split targets the previous row's anchor; size
    # percentages ensure all rows end up the same height.
    for r_idx in range(1, len(sizes)):
        remaining_rows_after = len(sizes) - 1 - (r_idx - 1)  # rows still to add
        parent_holds_rows = len(sizes) - (r_idx - 1)
        size = max(1, min(99, (remaining_rows_after * 100) // parent_holds_rows))
        if plan_idx >= len(plans):
            break
        title, cwd, cmd, _ = plans[plan_idx]
        plan_idx += 1
        ok, new_anchor = tmux.split_window_with_id(
            row_anchors[-1], cwd, cmd, vertical=True, size_percent=size,
        )
        if not ok:
            messages.append(f"split-window for {title} failed")
            continue
        tmux.set_pane_title(new_anchor, title)
        messages.append(f"{wname} -> {title} ({cwd})")
        row_anchors.append(new_anchor)

    # Step 2: for each row, split its anchor horizontally into `cols`
    # equal-width panes. The anchor already counts as pane #1 of the
    # row, so we only need `cols - 1` extra splits per row.
    for r_idx, row_anchor in enumerate(row_anchors):
        cols = sizes[r_idx]
        needed = cols - 1
        if needed <= 0:
            continue
        row_plans: list[tuple[str, str, str | None, bool]] = []
        for _ in range(needed):
            if plan_idx >= len(plans):
                break
            row_plans.append(plans[plan_idx])
            plan_idx += 1
        _fill_row(wname, row_anchor, row_plans, target_cols=cols, messages=messages)


def _pane_command(p: Project) -> str:
    """Project pane command — stream this project's dispatch events.

    Observation panes are read-only: the pty drops `echo` and
    canonical input so keystrokes produce no output, stdin comes from
    /dev/null so the watch can't read them either, and the pane ends
    in `sleep infinity` instead of a live shell so nothing is waiting
    to accept commands.
    """
    return (
        "sh -c '"
        "stty -echo -icanon 2>/dev/null; "
        f"central-mcp watch {p.name} </dev/null; "
        "stty echo icanon 2>/dev/null; "
        "sleep infinity"
        "'"
    )


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

    # Size the tmux session to the invoking terminal. Without this,
    # `new-session -d` defaults to 80×24 and any layout we build is
    # scaled when a larger client attaches — and tmux's rescaling does
    # NOT preserve the equal-width / orch-column ratios we set via
    # `-l N%` splits. Capturing the current terminal dimensions at
    # session creation time keeps those ratios intact at attach time.
    import shutil as _shutil
    _term_cols, _term_rows = _shutil.get_terminal_size(fallback=(200, 50))

    if not plan:
        messages.append("registry.yaml has no projects and no orchestrator — creating empty session")
        r = tmux.new_session(
            SESSION, window_name(0), ".",
            width=_term_cols, height=_term_rows,
        )
        if not r.ok:
            messages.append(f"new-session failed: {r.stderr.strip()}")
            return False, messages
        return True, messages

    # Chunk into windows. Every window holds up to `panes_per_window`
    # panes — the orchestrator is no longer special-cased, so it just
    # occupies the first cell of the first window and shares width
    # equally with any row-mates.
    chunks: list[list[tuple[str, str, str | None, bool]]] = [
        plan[i:i + panes_per_window]
        for i in range(0, len(plan), panes_per_window)
    ]

    for win_idx, chunk in enumerate(chunks):
        wname = window_name(win_idx, has_orchestrator=has_orchestrator)
        target = f"{SESSION}:{wname}"
        first_title, first_cwd, first_cmd, first_is_orch = chunk[0]

        if win_idx == 0:
            r = tmux.new_session(
                SESSION, wname, first_cwd, command=first_cmd,
                width=_term_cols, height=_term_rows,
            )
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

        # For the orchestrator's own tab (first window, has_orch=True),
        # give the orchestrator a full-height left column sized to one
        # project column. Overflow windows stay on the flat grid.
        # Narrow terminals can't host an orch-column layout (the
        # column would fall below the readable-width floor), so they
        # also fall back to the flat vertical-stack grid.
        from central_mcp.grid import pick_rows, _MIN_PANE_COLS
        narrow = _term_cols < 2 * _MIN_PANE_COLS
        if win_idx == 0 and first_is_orch and not narrow:
            _fill_orch_column_grid(
                target, wname, f"{target}.0", chunk[1:], messages,
            )
        else:
            rows = pick_rows(len(chunk), term_size=(_term_cols, _term_rows))
            _fill_grid(target, wname, f"{target}.0", chunk[1:], rows, messages)

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
