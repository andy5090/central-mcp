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

from central_mcp.layout import (
    DEFAULT_PANES_PER_WINDOW,
    OrchestratorPane,
    WINDOW_BASE,
    HUB_SUFFIX,
    window_name,
)
from central_mcp.registry import Project, load_registry

SESSION = "central"


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
    # Small counts (n <= rows) collapse to a single row side-by-side —
    # wide screens benefit from filling horizontal space first.
    if n <= rows:
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


def _tab_kdl(tab_name: str, panes: list[str], rows: int) -> str:
    """Render a tab whose panes fill the tab area as an equal-size grid.

    There's no hub-specific geometry anymore — the orchestrator (when
    present) is just the first pane, and every pane in the same row
    gets the same width. Users who want the orchestrator larger can
    manually resize inside zellij; the default no longer forces a 50%
    left column.
    """
    if not panes:
        return f'tab name={_kdl_escape(tab_name)} {{\n    pane\n}}'
    grid = _tile_panes(panes, rows=rows)
    return (
        f'tab name={_kdl_escape(tab_name)} {{\n'
        + _indent(grid, "    ")
        + '\n}'
    )


def build_layout(
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
    term_size: tuple[int, int] | None = None,
) -> str:
    """Build the full KDL layout string for the current registry.

    Every tab uses the same flat grid: the orchestrator (when present)
    is just the first pane in the first tab, and every pane in the
    same row gets an equal width. Rows per tab are chosen by
    `grid.pick_rows` based on terminal size, so a wide terminal gets
    a 2×N grid and a narrow terminal gets a taller grid.
    """
    if panes_per_window < 1:
        raise ValueError(f"panes_per_window must be >= 1, got {panes_per_window}")

    from central_mcp.grid import pick_rows

    has_orchestrator = orchestrator is not None
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
        for tab_idx, chunk in enumerate(chunks):
            tab_rows = pick_rows(len(chunk), term_size=term_size)
            tabs.append(_tab_kdl(
                window_name(tab_idx, has_orchestrator=has_orchestrator),
                chunk,
                rows=tab_rows,
            ))

    body = "\n".join(tabs)
    # `default_tab_template` pins the tab-bar plugin to the bottom of
    # every tab. Bottom placement keeps the first row of every pane
    # (command banner, prompt) at the actual top of the terminal where
    # the eye lands first; tab labels live on the edge the mouse and
    # status-bar conventions already put there.
    template = (
        'default_tab_template {\n'
        '    children\n'
        '    pane size=1 borderless=true {\n'
        '        plugin location="tab-bar"\n'
        '    }\n'
        '}'
    )
    return "layout {\n" + template + "\n" + body + "\n}\n"


def write_layout(
    path: Path,
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
) -> Path:
    """Write the generated KDL layout to disk and return the path."""
    kdl = build_layout(orchestrator=orchestrator, panes_per_window=panes_per_window)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(kdl)
    return path


def ensure_session(
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
    layout_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Start the Zellij session if missing, using a generated KDL layout.

    Returns (created, messages). Idempotent — if the session already
    exists, no layout is written and we just report that.
    """
    messages: list[str] = []
    if has_session(SESSION):
        messages.append(f"session '{SESSION}' already exists — leaving as-is")
        return False, messages

    if layout_path is None:
        from central_mcp import paths
        layout_path = paths.central_mcp_home() / "zellij-layout.kdl"
    write_layout(
        layout_path,
        orchestrator=orchestrator,
        panes_per_window=panes_per_window,
    )
    messages.append(f"wrote layout: {layout_path}")
    messages.append(f"session '{SESSION}' — attach with: central-mcp zellij")
    return True, messages
