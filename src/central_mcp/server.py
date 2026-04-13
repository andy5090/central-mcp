from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from central_mcp import tmux
from central_mcp.adapters import get_adapter
from central_mcp.registry import Project, find_project, load_registry


mcp = FastMCP("central-mcp")

ROOT = Path(__file__).resolve().parents[2]
LOG_ROOT = ROOT / "logs"
_logging_enabled: set[str] = set()  # tmux targets that have pipe-pane wired up


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


@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List every project registered in registry.yaml."""
    return [p.to_dict() for p in load_registry()]


@mcp.tool()
def project_status(name: str, lines: int = 60) -> dict[str, Any]:
    """Return registry info plus the last `lines` of the project's tmux pane output."""
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

    Guards:
      - pane must exist
      - pane must not be in copy-mode (user is scrolling/selecting)
      - set force=True to bypass the copy-mode guard

    Does NOT wait for completion. Poll project_status / fetch_logs afterwards.
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
def fetch_logs(name: str, lines: int = 500, source: str = "pane") -> dict[str, Any]:
    """Retrieve recent output from a project.

    source="pane": live scrollback via tmux capture-pane (bounded by scrollback size).
    source="file": full pipe-pane log file at logs/<name>/pane.log — survives scrollback loss.
    """
    project, err = _require_project(name)
    if err:
        return err
    target = project.tmux.target

    if source == "file":
        log_path = LOG_ROOT / project.name / "pane.log"
        if not log_path.exists():
            return {"ok": False, "error": f"no log file at {log_path}"}
        text = log_path.read_text(errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        return {"ok": True, "source": "file", "path": str(log_path), "log": tail}

    if not tmux.pane_exists(target):
        return {"ok": False, "error": f"pane {target} not found"}
    _ensure_logging(project)
    cap = tmux.capture_pane(target, lines=lines)
    return {
        "ok": cap.ok,
        "source": "pane",
        "target": target,
        "log": cap.stdout if cap.ok else cap.stderr,
    }


@mcp.tool()
def start_project(name: str) -> dict[str, Any]:
    """Launch the project's configured agent CLI inside its tmux pane.

    Refuses if the pane is already running something other than a shell —
    detected via `pane_current_command`. Use project_status to inspect first.
    """
    project, err = _require_project(name)
    if err:
        return err
    target = project.tmux.target
    if not tmux.pane_exists(target):
        return {"ok": False, "error": f"pane {target} not found — run bin/central-up.sh first"}

    current = tmux.pane_current_command(target)
    # Common shell names — anything else means something is already running.
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
