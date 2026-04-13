from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from central_mcp import tmux
from central_mcp.registry import find_project, load_registry


mcp = FastMCP("central-mcp")


@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List every project registered in registry.yaml."""
    return [p.to_dict() for p in load_registry()]


@mcp.tool()
def project_status(name: str, lines: int = 60) -> dict[str, Any]:
    """Return registry info plus the last `lines` of the project's tmux pane output."""
    project = find_project(name)
    if project is None:
        return {"ok": False, "error": f"unknown project: {name}"}
    target = project.tmux.target
    alive = tmux.pane_exists(target)
    log_tail = ""
    if alive:
        cap = tmux.capture_pane(target, lines=lines)
        log_tail = cap.stdout if cap.ok else cap.stderr
    return {
        "ok": True,
        "project": project.to_dict(),
        "pane_alive": alive,
        "log_tail": log_tail,
    }


@mcp.tool()
def dispatch_query(name: str, prompt: str, enter: bool = True) -> dict[str, Any]:
    """Send a prompt into the project's tmux pane as keystrokes.

    Does NOT wait for completion — call project_status afterwards to poll output.
    Returns immediately after the keystrokes are delivered.
    """
    project = find_project(name)
    if project is None:
        return {"ok": False, "error": f"unknown project: {name}"}
    target = project.tmux.target
    if not tmux.pane_exists(target):
        return {
            "ok": False,
            "error": f"tmux pane {target} not found — is the project running?",
        }
    result = tmux.send_keys(target, prompt, enter=enter)
    return {
        "ok": result.ok,
        "target": target,
        "stderr": result.stderr if not result.ok else "",
    }


@mcp.tool()
def fetch_logs(name: str, lines: int = 500) -> dict[str, Any]:
    """Capture up to `lines` of scrollback from the project's tmux pane."""
    project = find_project(name)
    if project is None:
        return {"ok": False, "error": f"unknown project: {name}"}
    target = project.tmux.target
    if not tmux.pane_exists(target):
        return {"ok": False, "error": f"pane {target} not found"}
    cap = tmux.capture_pane(target, lines=lines)
    return {
        "ok": cap.ok,
        "target": target,
        "log": cap.stdout if cap.ok else cap.stderr,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
