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


def _hub_tab_kdl(tab_name: str, orch_pane: str, project_panes: list[str]) -> str:
    """Hub tab: orchestrator on left, projects stacked on the right.

    Mirrors tmux main-vertical 50% via Zellij's `split_direction="vertical"`
    at the tab root with two children that divide the horizontal axis.
    """
    indent = "        "
    right_children = "\n".join(
        "\n".join(indent + ln for ln in p.splitlines()) for p in project_panes
    )
    orch_indented = "\n".join("        " + ln for ln in orch_pane.splitlines())
    right_block = (
        "    pane split_direction=\"horizontal\" {\n"
        f"{right_children}\n"
        "    }"
        if project_panes
        else ""
    )
    return (
        f'tab name={_kdl_escape(tab_name)} {{\n'
        '    pane split_direction="vertical" {\n'
        f'{orch_indented}\n'
        f'{right_block}\n'
        '    }\n'
        '}'
    )


def _indent(s: str, prefix: str) -> str:
    return "\n".join(prefix + ln for ln in s.splitlines())


def _tile_panes(panes: list[str], cols: int = 2) -> str:
    """Arrange project panes into a 2-column grid.

    Zellij doesn't have a `tiled` layout primitive, so we build the
    grid explicitly: an outer horizontal split (rows stacked top-to-
    bottom), each row being a vertical split (panes side-by-side).
    Single-pane and single-row cases degrade cleanly.
    """
    if not panes:
        return ""
    if len(panes) == 1:
        return panes[0]

    rows = [panes[i:i + cols] for i in range(0, len(panes), cols)]

    if len(rows) == 1:
        inner = "\n".join(_indent(p, "    ") for p in rows[0])
        return f'pane split_direction="vertical" {{\n{inner}\n}}'

    row_blocks: list[str] = []
    for row in rows:
        if len(row) == 1:
            row_blocks.append(_indent(row[0], "    "))
        else:
            inner = "\n".join(_indent(p, "        ") for p in row)
            row_blocks.append(
                f'    pane split_direction="vertical" {{\n{inner}\n    }}'
            )
    return (
        'pane split_direction="horizontal" {\n'
        + "\n".join(row_blocks)
        + '\n}'
    )


def _project_tab_kdl(tab_name: str, project_panes: list[str]) -> str:
    """Overflow tab: project panes tiled in a 2-column grid."""
    grid = _tile_panes(project_panes, cols=2)
    return (
        f'tab name={_kdl_escape(tab_name)} {{\n'
        + _indent(grid, "    ")
        + '\n}'
    )


def build_layout(
    orchestrator: OrchestratorPane | None = None,
    panes_per_window: int = DEFAULT_PANES_PER_WINDOW,
) -> str:
    """Build the full KDL layout string for the current registry.

    Mirrors `layout.ensure_session`'s chunking rules:
      - Hub tab with orchestrator + (panes_per_window - 1) project panes.
      - Overflow tabs with up to panes_per_window project panes each.
    """
    if panes_per_window < 1:
        raise ValueError(f"panes_per_window must be >= 1, got {panes_per_window}")

    has_orchestrator = orchestrator is not None
    projects = load_registry()

    orch_kdl = (
        _command_pane("Central MCP Orchestrator", orchestrator.cwd, orchestrator.command)
        if orchestrator is not None else None
    )
    project_kdls = [
        _command_pane(p.name, p.path, f"central-mcp watch {p.name}", readonly=True)
        for p in projects
    ]

    # Orchestrator visually takes two cells (it's the wide left pane in
    # the hub split), so the hub window matches the tmux contract: total
    # panes = panes_per_window - 1 (= orch + panes_per_window - 2 projects).
    # Overflow windows still take the full panes_per_window projects.
    if has_orchestrator:
        hub_project_count = max(panes_per_window - 2, 0)
    else:
        hub_project_count = panes_per_window

    hub_projects = project_kdls[:hub_project_count] if has_orchestrator else []
    overflow_start = hub_project_count if has_orchestrator else 0
    overflow = project_kdls[overflow_start:]

    tabs: list[str] = []
    if has_orchestrator:
        tabs.append(_hub_tab_kdl(
            window_name(0, has_orchestrator=True),
            orch_kdl,
            hub_projects,
        ))
    elif not project_kdls:
        # Empty registry + no orchestrator → still create a tab so zellij
        # has something to show.
        tabs.append(f'tab name={_kdl_escape(window_name(0))} {{\n    pane\n}}')

    for i in range(0, len(overflow), panes_per_window):
        idx = (1 if has_orchestrator else 0) + (i // panes_per_window)
        if not has_orchestrator and idx == 0 and not tabs:
            tabs.append(_project_tab_kdl(window_name(0), overflow[i:i + panes_per_window]))
            continue
        tabs.append(_project_tab_kdl(
            window_name(idx, has_orchestrator=has_orchestrator),
            overflow[i:i + panes_per_window],
        ))

    # When no orchestrator AND projects fit in one tab, the loop already
    # handled it; otherwise fall through.

    body = "\n".join(tabs) if tabs else 'tab name="cmcp-1" {\n    pane\n}'
    # `default_tab_template` ensures every tab has zellij's standard
    # tab-bar + status-bar plugins so shortcut hints show up at top
    # and bottom, same as the layout zellij boots with by default.
    # `compact-bar` is the slim status plugin — it shows zellij's
    # shortcut hints at the bottom without the extra "ENTER to rerun /
    # ESC to drop to shell" controls that `status-bar` adds on top of
    # `command=` panes.
    template = (
        'default_tab_template {\n'
        '    pane size=1 borderless=true {\n'
        '        plugin location="tab-bar"\n'
        '    }\n'
        '    children\n'
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
