from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from central_mcp import tmux
from central_mcp.adapters import get_adapter
from central_mcp.registry import (
    Project,
    add_project as _registry_add,
    find_project,
    load_registry,
    remove_project as _registry_remove,
)
from central_mcp.scrub import scrub


_MCP_INSTRUCTIONS = """\
You are connected to central-mcp, a multi-project orchestration hub for
coding agents. This hub manages a registry of projects; each project runs
in its own tmux pane, typically with a coding-agent CLI (Claude Code,
Codex, Cursor, Gemini) attached.

When the user asks anything about "my projects", status, dispatching work,
fetching logs, or hub-wide activity, call these tools:

  - list_projects       — enumerate the registry
  - project_status      — pane liveness + recent output for one project
  - project_activity    — busy / recent / idle state
  - dispatch_query      — send a prompt into a project's pane as keystrokes
  - fetch_logs          — retrieve recent output (pane or persisted file)
  - start_project       — launch the configured agent CLI in a pane
  - add_project / remove_project — edit the registry

When the user says something like "what's running?", "send this to X",
"how is gluecut-dawg doing?", assume they mean one of the registered
projects and call list_projects first to see what is available. The
orchestrator (you) is NOT the only agent — you dispatch work to other
agents running in their own panes and observe their output.
"""

mcp = FastMCP("central-mcp", instructions=_MCP_INSTRUCTIONS)

ROOT = Path(__file__).resolve().parents[2]
LOG_ROOT = ROOT / "logs"
_logging_enabled: set[str] = set()


def _ensure_logging(project: Project) -> None:
    target = project.tmux.target
    if target in _logging_enabled:
        return
    log_path = LOG_ROOT / project.name / "pane.log"
    r = tmux.pipe_pane_to_file(target, log_path)
    if r.ok:
        _logging_enabled.add(target)


def _require_project(name: str) -> tuple[Project | None, dict[str, Any] | None]:
    project = find_project(name)
    if project is None:
        return None, {"ok": False, "error": f"unknown project: {name}"}
    return project, None


def _log_path(project: Project) -> Path:
    return LOG_ROOT / project.name / "pane.log"


@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List every project registered in registry.yaml."""
    return [p.to_dict() for p in load_registry()]


@mcp.tool()
def project_status(
    name: str,
    lines: int = 60,
    scrub_ansi: bool = True,
    scrub_secrets: bool = True,
) -> dict[str, Any]:
    """Return registry info plus the last `lines` of the pane output."""
    project, err = _require_project(name)
    if err:
        return err
    target = project.tmux.target
    alive = tmux.pane_exists(target)
    log_tail = ""
    current_cmd = ""
    if alive:
        _ensure_logging(project)
        cap = tmux.capture_pane(target, lines=lines)
        log_tail = cap.stdout if cap.ok else cap.stderr
        log_tail = scrub(log_tail, ansi=scrub_ansi, secrets=scrub_secrets)
        current_cmd = tmux.pane_current_command(target)
    return {
        "ok": True,
        "project": project.to_dict(),
        "pane_alive": alive,
        "pane_current_command": current_cmd,
        "log_tail": log_tail,
    }


@mcp.tool()
def dispatch_query(
    name: str,
    prompt: str,
    enter: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Send a prompt into the project's tmux pane as keystrokes.

    Guards against copy-mode (user scrolling). Override with force=True.
    Does NOT wait for completion — poll project_status / fetch_logs afterwards.
    """
    project, err = _require_project(name)
    if err:
        return err
    target = project.tmux.target
    if not tmux.pane_exists(target):
        return {"ok": False, "error": f"tmux pane {target} not found — is the project running?"}
    if not force and tmux.pane_in_copy_mode(target):
        return {
            "ok": False,
            "error": (
                f"pane {target} is in copy-mode (user appears to be scrolling). "
                "Retry with force=true to override."
            ),
        }
    _ensure_logging(project)
    result = tmux.send_keys(target, prompt, enter=enter)
    return {
        "ok": result.ok,
        "target": target,
        "stderr": result.stderr if not result.ok else "",
    }


@mcp.tool()
def fetch_logs(
    name: str,
    lines: int = 500,
    source: str = "pane",
    scrub_ansi: bool = True,
    scrub_secrets: bool = True,
) -> dict[str, Any]:
    """Retrieve recent output from a project.

    source="pane": live scrollback via capture-pane (bounded by scrollback size).
    source="file": full pipe-pane log at logs/<name>/pane.log — survives scrollback loss.
    """
    project, err = _require_project(name)
    if err:
        return err
    target = project.tmux.target

    if source == "file":
        log_path = _log_path(project)
        if not log_path.exists():
            return {"ok": False, "error": f"no log file at {log_path}"}
        text = log_path.read_text(errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        tail = scrub(tail, ansi=scrub_ansi, secrets=scrub_secrets)
        return {"ok": True, "source": "file", "path": str(log_path), "log": tail}

    if not tmux.pane_exists(target):
        return {"ok": False, "error": f"pane {target} not found"}
    _ensure_logging(project)
    cap = tmux.capture_pane(target, lines=lines)
    log = cap.stdout if cap.ok else cap.stderr
    log = scrub(log, ansi=scrub_ansi, secrets=scrub_secrets)
    return {"ok": cap.ok, "source": "pane", "target": target, "log": log}


@mcp.tool()
def start_project(name: str) -> dict[str, Any]:
    """Launch the project's configured agent CLI inside its tmux pane.

    Refuses if the pane is already running something other than a shell.
    """
    project, err = _require_project(name)
    if err:
        return err
    target = project.tmux.target
    if not tmux.pane_exists(target):
        return {"ok": False, "error": f"pane {target} not found — run bin/central-up.sh first"}

    current = tmux.pane_current_command(target)
    shells = {"zsh", "bash", "fish", "sh", "dash"}
    if current and current not in shells:
        return {
            "ok": False,
            "error": f"pane is running '{current}'; refuse to start a second agent on top",
        }

    adapter = get_adapter(project.agent)
    cmd = adapter.launch_command()
    if not cmd:
        return {"ok": True, "note": f"adapter '{project.agent}' has no launch command (shell)"}

    _ensure_logging(project)
    r = tmux.send_keys(target, cmd, enter=True)
    return {
        "ok": r.ok,
        "target": target,
        "launched": cmd,
        "stderr": r.stderr if not r.ok else "",
    }


@mcp.tool()
def project_activity(name: str) -> dict[str, Any]:
    """Estimate how active a project pane is.

    Uses (a) the current foreground process and (b) the mtime of the
    pipe-pane log file. Returns one of:
      busy   — log updated within last 2s
      recent — log updated within last 30s
      idle   — older than 30s or no log yet
    """
    project, err = _require_project(name)
    if err:
        return err
    target = project.tmux.target
    alive = tmux.pane_exists(target)
    current = tmux.pane_current_command(target) if alive else ""

    log_path = _log_path(project)
    if not log_path.exists():
        return {
            "ok": True, "name": name, "pane_alive": alive,
            "current_command": current, "state": "unknown",
            "last_activity_sec": None,
        }

    _ensure_logging(project)  # make sure logging is on so future polls see updates
    age = time.time() - log_path.stat().st_mtime
    if age < 2:
        state = "busy"
    elif age < 30:
        state = "recent"
    else:
        state = "idle"
    return {
        "ok": True,
        "name": name,
        "pane_alive": alive,
        "current_command": current,
        "state": state,
        "last_activity_sec": round(age, 1),
    }


@mcp.tool()
def add_project(
    name: str,
    path: str,
    agent: str = "shell",
    session: str = "central",
    window: str = "projects",
    pane: int | None = None,
    description: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Append a project to registry.yaml. Does NOT create its tmux pane —
    rerun bin/central-up.sh (after killing the old session) to materialize
    the layout, or manually split the projects window.
    """
    try:
        proj = _registry_add(
            name=name, path_=path, agent=agent, session=session,
            window=window, pane=pane, description=description, tags=tags,
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "project": proj.to_dict(),
        "note": "registry.yaml updated; rerun central-up.sh to rebuild layout if needed",
    }


@mcp.tool()
def remove_project(name: str) -> dict[str, Any]:
    """Remove a project from registry.yaml. Leaves tmux panes untouched."""
    removed = _registry_remove(name)
    if not removed:
        return {"ok": False, "error": f"project {name!r} not found in registry"}
    return {"ok": True, "removed": name}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
