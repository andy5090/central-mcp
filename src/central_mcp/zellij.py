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


def _command_pane(name: str, cwd: str, command: str) -> str:
    """Build a KDL `pane` block that runs a command in a cwd with a display name.

    The command arrives as a shell string — we split it into argv so
    Zellij's `command="…"` + `args` shape works (it does not pipe through
    a shell). That means simple `command_line arg1 arg2` is supported;
    shell operators like `;` / `&&` are not. Good enough for our watch/
    orchestrator invocations.
    """
    argv = shlex.split(command)
    if not argv:
        raise ValueError(f"empty command for pane {name!r}")
    head, *rest = argv
    lines = [
        f'pane name={_kdl_escape(name)} cwd={_kdl_escape(cwd)} command={_kdl_escape(head)} {{'
    ]
    if rest:
        args_kdl = " ".join(_kdl_escape(a) for a in rest)
        lines.append(f"    args {args_kdl}")
    lines.append("}")
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


def _project_tab_kdl(tab_name: str, project_panes: list[str]) -> str:
    """Overflow tab: project panes stacked horizontally (vertical stack)."""
    indent = "    "
    children = "\n".join(
        "\n".join(indent + ln for ln in p.splitlines()) for p in project_panes
    )
    return (
        f'tab name={_kdl_escape(tab_name)} {{\n'
        '    pane split_direction="horizontal" {\n'
        f'{children}\n'
        '    }\n'
        '}'
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
        _command_pane(p.name, p.path, f"central-mcp watch {p.name}")
        for p in projects
    ]

    hub_project_count = (panes_per_window - 1) if has_orchestrator else panes_per_window
    hub_project_count = max(hub_project_count, 1)

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
    return "layout {\n" + body + "\n}\n"


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
