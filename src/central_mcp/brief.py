"""Compact registry + activity brief — meant to be consumed by Claude Code
SessionStart hooks (or any other tool) as additional context.

Prints a short markdown block that any orchestrator can read at a glance:
project list with pane status, current foreground command, and rough
activity state. Safe to pipe straight into hook stdout.
"""

from __future__ import annotations

import time
from pathlib import Path

from central_mcp import tmux
from central_mcp.registry import Project, load_registry

_LOG_ROOT = Path(__file__).resolve().parents[2] / "logs"


def _activity(p: Project) -> tuple[str, str | None]:
    log_path = _LOG_ROOT / p.name / "pane.log"
    if not log_path.exists():
        return "unknown", None
    age = time.time() - log_path.stat().st_mtime
    if age < 2:
        return "busy", round(age, 1)
    if age < 30:
        return "recent", round(age, 1)
    return "idle", round(age, 1)


def _row(p: Project) -> str:
    target = p.tmux.target
    alive = tmux.pane_exists(target)
    if not alive:
        return f"- **{p.name}** — pane `{target}` ❌ not running"
    state, age = _activity(p)
    cmd = tmux.pane_current_command(target) or "-"
    age_str = f"{age}s ago" if age is not None else "never"
    return f"- **{p.name}** — `{target}` · {state} · cmd=`{cmd}` · last={age_str}"


def render() -> str:
    projects = load_registry()
    if not projects:
        return "## central-mcp\n\n_(registry.yaml is empty)_"
    lines = ["## central-mcp", "", f"_{len(projects)} project(s) registered_", ""]
    for p in projects:
        lines.append(_row(p))
    lines.append("")
    lines.append("Use MCP tools: `list_projects`, `project_status`, `dispatch_query`, `fetch_logs`, `project_activity`, `start_project`, `add_project`, `remove_project`.")
    return "\n".join(lines)


def main() -> int:
    print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
