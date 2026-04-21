"""Optional cmux observation layer (macOS-native GUI terminal).

`central-mcp cmux` builds a cmux workspace — cmux is a macOS AppKit /
Ghostty-based GUI terminal with vertical tabs and notifications,
distinct from tmux/zellij in that it's a GUI app talking over a Unix
socket (`~/.cmux/cmux.sock`). We only use its declarative surface
(`cmux new-workspace --layout <json>`); imperative RPC (send-text,
new-pane) is explicitly out of scope — orchestrator agents can call
the `cmux` CLI directly if they need that.

Because the layout tree is sized by the cmux GUI (not by char cells),
this module skips the terminal-size heuristics in `grid.pick_rows` —
cmux handles responsive sizing on its own. Tiling reduces to: ≤2
projects use a single split; ≥3 cascade; ≥4 form a 2-row grid.

The MCP dispatch path never depends on this layer; closing the
workspace has no effect on in-flight dispatches, same as tmux/zellij.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from central_mcp.layout import OrchestratorPane
from central_mcp.registry import Project, load_registry

SESSION = "central"


@dataclass
class CmuxResult:
    ok: bool
    stdout: str
    stderr: str


def _run(args: list[str]) -> CmuxResult:
    try:
        proc = subprocess.run(
            ["cmux", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return CmuxResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except FileNotFoundError:
        return CmuxResult(ok=False, stdout="", stderr="cmux not installed")


def ping() -> bool:
    """True if the cmux GUI's unix socket answers a ping."""
    return _run(["ping"]).ok


def list_workspaces() -> list[dict[str, Any]]:
    """Return all live workspaces, parsed from `cmux --json list-workspaces`.

    `--json` is a global flag in cmux's CLI and goes before the
    subcommand, so the call is `cmux --json list-workspaces` (not
    `cmux list-workspaces --json`). Returns `[]` on any failure —
    binary missing, socket unreachable, unparseable output — so
    callers can treat the result as "no workspaces".
    """
    r = _run(["--json", "list-workspaces"])
    if not r.ok:
        return []
    try:
        payload = json.loads(r.stdout)
    except (ValueError, json.JSONDecodeError):
        return []
    ws = payload.get("workspaces") if isinstance(payload, dict) else None
    return ws if isinstance(ws, list) else []


def has_workspace(name: str) -> bool:
    """True if a workspace whose title is `name` is open in cmux."""
    for ws in list_workspaces():
        if isinstance(ws, dict) and ws.get("title") == name:
            return True
    return False


def _find_workspace_handle(name: str) -> str | None:
    """Return a handle (preferring the `workspace:N` ref form, falling
    back to the UUID `id`) for the workspace titled `name`, or None.
    cmux's `close-workspace --workspace` accepts either form."""
    for ws in list_workspaces():
        if not isinstance(ws, dict) or ws.get("title") != name:
            continue
        ref = ws.get("ref")
        if isinstance(ref, str) and ref:
            return ref
        wid = ws.get("id")
        if isinstance(wid, str) and wid:
            return wid
    return None


def kill_workspace(name: str) -> CmuxResult:
    """Close the workspace titled `name` if present.

    cmux's `close-workspace` takes `--workspace <id|ref|index>`, not a
    title, so we resolve via `list-workspaces` first. When no matching
    workspace exists returns `ok=True` with an informational stderr,
    matching the tmux / zellij no-op contract.
    """
    handle = _find_workspace_handle(name)
    if handle is None:
        return CmuxResult(ok=True, stdout="", stderr=f"no workspace titled {name!r}")
    return _run(["close-workspace", "--workspace", handle])


# ---------- layout JSON builders ----------

def _readonly_command(name: str) -> str:
    """Match the zellij `_command_pane(... readonly=True)` wrap so
    project panes behave the same across backends: stdin disconnected,
    pty echo off, watch command captures output, pane hangs on
    `sleep infinity` instead of dropping to a shell."""
    return (
        f"stty -echo -icanon 2>/dev/null; "
        f"central-mcp watch {name} </dev/null; "
        "stty echo icanon 2>/dev/null; "
        "sleep infinity"
    )


def _orch_command(command: str) -> str:
    """Wrap orchestrator command so the pane survives agent exit."""
    return f"{command}; exec $SHELL"


def _terminal_surface(
    name: str, cwd: str, command: str, *, focus: bool = False,
) -> dict[str, Any]:
    s: dict[str, Any] = {
        "type": "terminal",
        "name": name,
        "cwd": cwd,
        "command": command,
    }
    if focus:
        s["focus"] = True
    return s


def _pane(
    name: str, cwd: str, command: str, *, focus: bool = False,
) -> dict[str, Any]:
    return {"surfaces": [_terminal_surface(name, cwd, command, focus=focus)]}


def _split(
    direction: str,
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    split: float = 0.5,
) -> dict[str, Any]:
    return {
        "direction": direction,
        "split": split,
        "first": first,
        "second": second,
    }


def _project_panes(projects: list[Project]) -> list[dict[str, Any]]:
    return [_pane(p.name, p.path, _readonly_command(p.name)) for p in projects]


def _tile_row(panes: list[dict[str, Any]]) -> dict[str, Any]:
    """Horizontal cascade — panes side-by-side within one row."""
    if len(panes) == 1:
        return panes[0]
    if len(panes) == 2:
        return _split("horizontal", panes[0], panes[1])
    return _split("horizontal", panes[0], _tile_row(panes[1:]))


def _tile_projects(panes: list[dict[str, Any]]) -> dict[str, Any]:
    """Recursive tiler over project pane leaves. ≤2 panes use a single
    split; ≥3 cascade; ≥4 form a 2-row grid. Stays well under 40 lines
    because cmux is a GUI — no char-cell math, just structural shape.
    """
    n = len(panes)
    if n == 1:
        return panes[0]
    if n == 2:
        return _split("horizontal", panes[0], panes[1])
    if n == 3:
        return _split("vertical", panes[0], _split("horizontal", panes[1], panes[2]))
    mid = (n + 1) // 2
    return _split("vertical", _tile_row(panes[:mid]), _tile_row(panes[mid:]))


def build_layout_json(
    orchestrator: OrchestratorPane | None,
    projects: list[Project],
) -> dict[str, Any]:
    """Produce the JSON dict passed to `cmux new-workspace --layout`.

    Branches:
      - Empty registry AND no orchestrator → one empty terminal surface.
      - Orchestrator + ≥1 project → horizontal split, orch on left,
        project subtree on right.
      - Orchestrator only → a single pane leaf.
      - No orchestrator, N projects → project subtree; first surface
        gets focus so cmux lands the user on p0.
    """
    if orchestrator is None and not projects:
        layout: dict[str, Any] = {"surfaces": [{"type": "terminal", "focus": True}]}
    elif orchestrator is not None and projects:
        orch_pane = _pane(
            "Central MCP Orchestrator",
            orchestrator.cwd,
            _orch_command(orchestrator.command),
            focus=True,
        )
        projects_tree = _tile_projects(_project_panes(projects))
        layout = _split("horizontal", orch_pane, projects_tree)
    elif orchestrator is not None:
        layout = _pane(
            "Central MCP Orchestrator",
            orchestrator.cwd,
            _orch_command(orchestrator.command),
            focus=True,
        )
    else:
        panes = _project_panes(projects)
        panes[0]["surfaces"][0]["focus"] = True
        layout = _tile_projects(panes)
    return {
        "name": SESSION,
        "cwd": ".",
        "layout": layout,
    }


def ensure_workspace(
    orchestrator: OrchestratorPane | None = None,
) -> tuple[bool, list[str]]:
    """Idempotently open the cmux workspace for the current registry.

    Returns `(created, messages)`. `created` is False when the
    workspace is already open (no-op) and True when cmux accepted a
    fresh `new-workspace` call. Subprocess failures are surfaced in
    `messages` (not raised) so callers can report them in line with
    the tmux / zellij backends.
    """
    messages: list[str] = []
    if has_workspace(SESSION):
        messages.append(f"workspace '{SESSION}' already exists — leaving as-is")
        return False, messages

    projects = load_registry()
    layout = build_layout_json(orchestrator, projects)
    r = _run([
        "new-workspace",
        "--name", SESSION,
        "--layout", json.dumps(layout),
    ])
    if not r.ok:
        detail = (r.stderr or r.stdout or "").strip()
        messages.append(
            f"cmux new-workspace failed{': ' + detail if detail else ''}"
        )
        return False, messages
    messages.append(f"workspace '{SESSION}' opened via cmux")
    return True, messages
