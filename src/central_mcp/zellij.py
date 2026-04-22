"""Optional Zellij observation layer (parallels `layout.py` for tmux).

`central-mcp zellij` builds a KDL layout file that mirrors the tmux
story: a hub tab (`cmcp-1-hub`) whose left half is the orchestrator
pane and whose right half stacks the first project panes, plus
overflow tabs (`cmcp-2`, `cmcp-3`, …) with up to
`DEFAULT_PANES_PER_WINDOW` project panes each.

Each pane is an explicit `name=` + `cwd=` + `command=` declaration so
Zellij's built-in tab bar shows meaningful labels out of the box — we
don't need per-pane styling hacks the way we did in tmux.

The MCP dispatch path never depends on this layer; killing the
session has no effect on in-flight dispatches, same as tmux.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from central_mcp.grid import pick_panes_per_window, pick_rows
from central_mcp.layout import (
    DEFAULT_PANES_PER_WINDOW,
    LEGACY_SESSION,
    OrchestratorPane,
    SESSION_PREFIX,
    WINDOW_BASE,
    HUB_SUFFIX,
    session_name_for_workspace,
    window_name,
)
from central_mcp.registry import Project, load_registry

SESSION = LEGACY_SESSION  # kept for backward-compat imports


@dataclass
class ZellijResult:
    ok: bool
    stdout: str
    stderr: str


def _run(args: list[str]) -> ZellijResult:
    try:
        proc = subprocess.run(
            ["zellij", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return ZellijResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except FileNotFoundError:
        return ZellijResult(ok=False, stdout="", stderr="zellij not installed")


def list_sessions() -> list[str]:
    """Return active session names. Empty on error or no sessions."""
    r = _run(["list-sessions", "--short"])
    if not r.ok:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def has_session(name: str) -> bool:
    return name in list_sessions()


def kill_session(name: str) -> ZellijResult:
    return _run(["kill-session", name])


def _kdl_escape(s: str) -> str:
    """Quote a KDL string value. KDL accepts double-quoted strings with
    standard escape sequences; for commands/paths with spaces or special
    chars we need proper escaping."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _command_pane(name: str, cwd: str, command: str, readonly: bool = False) -> str:
    """Build a KDL `pane` block that runs a command in a cwd with a display name.

    When `readonly` is True (observation panes — `central-mcp watch`)
    the command runs with stdin from /dev/null and falls through to
    `sleep infinity` on exit so the pane stays alive but never drops
    into a shell that would accept keystrokes. When False (orchestrator
    pane), the command is wrapped in `sh -c '<cmd>; exec $SHELL'` so
    a human can keep typing after the agent exits, mirroring the tmux
    layer's pane-survival trick.
    """
    argv = shlex.split(command)
    if not argv:
        raise ValueError(f"empty command for pane {name!r}")
    quoted = " ".join(shlex.quote(a) for a in argv)
    if readonly:
        # `stty -echo -icanon` silences the pty so typing in the pane
        # has no visible effect; stdin from /dev/null makes sure the
        # watch command can't read input; `sleep infinity` keeps the
        # pane alive after watch exits without dropping to a shell.
        wrapped = (
            f"stty -echo -icanon 2>/dev/null; "
            f"{quoted} </dev/null; "
            "stty echo icanon 2>/dev/null; "
            "sleep infinity"
        )
    else:
        wrapped = f"{quoted}; exec $SHELL"
    lines = [
        f'pane name={_kdl_escape(name)} cwd={_kdl_escape(cwd)} command="sh" {{',
        f"    args \"-c\" {_kdl_escape(wrapped)}",
        "}",
    ]
    return "\n".join(lines)


def _indent(s: str, prefix: str) -> str:
    return "\n".join(prefix + ln for ln in s.splitlines())


def _tile_panes(panes: list[str], rows: int = 2) -> str:
    """Arrange panes in a grid with **at most `rows` rows**; columns
    grow horizontally as the pane count increases.

    Example progression for rows=2:
      n=1  → single pane
      n=2  → 1 row × 2 cols (side by side)
      n=3  → 2 rows (top 2, bottom 1)
      n=4  → 2 rows × 2 cols
      n=10 → 2 rows × 5 cols

    Zellij has no `tiled` primitive, so we emit nested splits: outer
    `split_direction="horizontal"` stacks rows top-to-bottom; each row
    is a `split_direction="vertical"` putting its panes side-by-side.
    """
    if not panes:
        return ""
    if len(panes) == 1:
        return panes[0]

    n = len(panes)
    # When the requested rows ≥ pane count the layout degenerates to
    # either a vertical stack (caller's `pick_rows` returned n meaning
    # "put them all in separate rows") or a single row. We detect the
    # vertical-stack intent by `rows == n` (pick_rows does that for
    # narrow terminals) and emit a horizontal-split block, which in
    # zellij's KDL conventions stacks children top-to-bottom.
    if rows >= n and rows > 1:
        inner = "\n".join(_indent(p, "    ") for p in panes)
        return f'pane split_direction="horizontal" {{\n{inner}\n}}'
    # Else if n fits in one row, side-by-side.
    if n <= rows or rows <= 1:
        inner = "\n".join(_indent(p, "    ") for p in panes)
        return f'pane split_direction="vertical" {{\n{inner}\n}}'

    cols_per_row = (n + rows - 1) // rows  # ceil(n / rows)
    groups: list[list[str]] = []
    for i in range(rows):
        start = i * cols_per_row
        if start >= n:
            break
        groups.append(panes[start:start + cols_per_row])

    row_blocks: list[str] = []
    for group in groups:
        if len(group) == 1:
            row_blocks.append(_indent(group[0], "    "))
        else:
            inner = "\n".join(_indent(p, "        ") for p in group)
            row_blocks.append(
                f'    pane split_direction="vertical" {{\n{inner}\n    }}'
            )
    return (
        'pane split_direction="horizontal" {\n'
        + "\n".join(row_blocks)
        + '\n}'
    )


def _tab_kdl(
    tab_name: str,
    panes: list[str],
    rows: int,
    *,
    orch_first: bool = False,
    term_size: tuple[int, int] | None = None,
) -> str:
    """Render a tab.

    When `orch_first=True` the first pane is treated as an
    orchestrator that gets its own full-height left column. The column
    is sized to match the width of one project-column in the project
    grid — so `orch + 1` reproduces the classic 50/50 layout, and
    `orch + N` gives each project column the same width as the
    orchestrator column (orchestrator no longer dominates with a hard
    50% when there are many projects).

    Without the flag, every pane gets an equal slot in the 2-row (or
    computed-row) grid — the 0.6.3 flat default.

    `term_size` forwards through to the internal `pick_rows` call
    used to shape the right-side project grid; without it that call
    would read the invoking terminal and may pick a different grid
    than the outer caller (who already decided based on its own
    `term_size`).
    """
    if not panes:
        return f'tab name={_kdl_escape(tab_name)} {{\n    pane\n}}'

    if orch_first and len(panes) >= 2:
        orch_pane, project_panes = panes[0], panes[1:]
        project_rows = pick_rows(len(project_panes), term_size=term_size)
        top_cols = (len(project_panes) + project_rows - 1) // project_rows
        orch_size = max(1, 100 // (top_cols + 1))
        project_grid = _tile_panes(project_panes, rows=project_rows)

        orch_sized = _inject_size(orch_pane, f"{orch_size}%")
        orch_indented = _indent(orch_sized, "        ")
        grid_indented = _indent(project_grid, "        ")
        return (
            f'tab name={_kdl_escape(tab_name)} {{\n'
            '    pane split_direction="vertical" {\n'
            f'{orch_indented}\n'
            f'{grid_indented}\n'
            '    }\n'
            '}'
        )

    grid = _tile_panes(panes, rows=rows)
    return (
        f'tab name={_kdl_escape(tab_name)} {{\n'
        + _indent(grid, "    ")
        + '\n}'
    )


def _inject_size(pane_block: str, size: str) -> str:
    """Insert a `size="N%"` attribute into the opening `pane` line of
    a KDL block. Safe to call on blocks that don't start with `pane` —
    the original string is returned untouched.
    """
    if not pane_block.startswith("pane"):
        return pane_block
    first_nl = pane_block.find("\n")
    first_line = pane_block[:first_nl] if first_nl != -1 else pane_block
    rest = pane_block[first_nl:] if first_nl != -1 else ""
    brace_idx = first_line.find("{")
    if brace_idx == -1:
        # Single-line `pane ...`: append size attribute at the end.
        return first_line.rstrip() + f' size="{size}"' + rest
    before_brace = first_line[:brace_idx].rstrip()
    brace_and_after = first_line[brace_idx:]
    return f'{before_brace} size="{size}" {brace_and_after}{rest}'


def build_layout(
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
    term_size: tuple[int, int] | None = None,
    projects: list[Project] | None = None,
) -> str:
    """Build the full KDL layout string for the current registry.

    The first tab puts the orchestrator (when present) in a full-
    height left column whose width matches one project column in the
    tab's project grid — so `orch + 1 project` reproduces a 50/50
    split, and `orch + N` lets each project column match the
    orchestrator column's width without the orchestrator dominating
    a hard 50%. Overflow tabs (no orchestrator) stay on the flat grid.

    `panes_per_window` defaults to the static constant; the CLI
    resolves `None` via `grid.pick_panes_per_window` before calling.
    `projects` defaults to `load_registry()`; pass a workspace-filtered
    list to scope to one workspace.
    """
    if panes_per_window < 1:
        raise ValueError(f"panes_per_window must be >= 1, got {panes_per_window}")

    has_orchestrator = orchestrator is not None
    if projects is None:
        projects = load_registry()

    pane_kdls: list[str] = []
    if orchestrator is not None:
        pane_kdls.append(
            _command_pane("Central MCP Orchestrator", orchestrator.cwd, orchestrator.command)
        )
    pane_kdls.extend(
        _command_pane(p.name, p.path, f"central-mcp watch {p.name}", readonly=True)
        for p in projects
    )

    tabs: list[str] = []
    if not pane_kdls:
        tabs.append(f'tab name={_kdl_escape(window_name(0))} {{\n    pane\n}}')
    else:
        chunks = [
            pane_kdls[i:i + panes_per_window]
            for i in range(0, len(pane_kdls), panes_per_window)
        ]
        # Narrow terminals can't host an orchestrator-column layout —
        # every column would fall below the readability floor. Fall
        # back to the flat grid where orchestrator is just the first
        # pane of a vertical stack on the first tab.
        import shutil as _shutil
        import central_mcp.grid as _grid
        effective_cols = term_size[0] if term_size else _shutil.get_terminal_size(fallback=(120, 40)).columns
        narrow = effective_cols < 2 * _grid._MIN_PANE_COLS
        for tab_idx, chunk in enumerate(chunks):
            tab_rows = pick_rows(len(chunk), term_size=term_size)
            is_first_with_orch = (tab_idx == 0 and has_orchestrator) and not narrow
            tabs.append(_tab_kdl(
                window_name(tab_idx, has_orchestrator=has_orchestrator),
                chunk,
                rows=tab_rows,
                orch_first=is_first_with_orch,
                term_size=term_size,
            ))

    body = "\n".join(tabs)
    # Match zellij's stock UX: `tab-bar` at the top (labels + active-
    # tab indicator) and `status-bar` at the bottom (mode indicator +
    # keybinding preset hints). Earlier releases stripped the status
    # bar entirely while moving the tab bar to the bottom, which
    # looked cleaner at a glance but cost new users the discoverability
    # of zellij's keybindings.
    template = (
        'default_tab_template {\n'
        '    pane size=1 borderless=true {\n'
        '        plugin location="tab-bar"\n'
        '    }\n'
        '    children\n'
        '    pane size=2 borderless=true {\n'
        '        plugin location="status-bar"\n'
        '    }\n'
        '}'
    )
    return "layout {\n" + template + "\n" + body + "\n}\n"


def write_layout(
    path: Path,
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
    projects: list[Project] | None = None,
) -> Path:
    """Write the generated KDL layout to disk and return the path."""
    kdl = build_layout(
        orchestrator=orchestrator,
        panes_per_window=panes_per_window,
        projects=projects,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(kdl)
    return path


def ensure_session(
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
    layout_path: Path | None = None,
    session_name: str | None = None,
    projects: list[Project] | None = None,
) -> tuple[bool, list[str]]:
    """Start the Zellij session if missing, using a generated KDL layout.

    Returns (created, messages). Idempotent — if the session already
    exists, no layout is written and we just report that.

    `session_name` defaults to `cmcp-<current_workspace>`.
    `projects` defaults to `load_registry()`; pass a workspace-filtered
    list to scope to one workspace.
    """
    if session_name is None:
        from central_mcp.registry import current_workspace
        session_name = session_name_for_workspace(current_workspace())

    messages: list[str] = []
    if has_session(session_name):
        messages.append(f"session '{session_name}' already exists — leaving as-is")
        return False, messages

    if layout_path is None:
        from central_mcp import paths
        layout_path = paths.central_mcp_home() / f"zellij-layout-{session_name}.kdl"
    write_layout(
        layout_path,
        orchestrator=orchestrator,
        panes_per_window=panes_per_window,
        projects=projects,
    )
    messages.append(f"wrote layout: {layout_path}")
    messages.append(f"session '{session_name}' — attach with: central-mcp zellij")
    return True, messages
