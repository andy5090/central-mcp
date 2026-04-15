"""Compact registry snapshot for SessionStart hooks and `central-mcp brief`.

Prints a short markdown block listing every registered project so the
orchestrator knows the hub surface at a glance. No pane state, no log
tailing — dispatch is subprocess-based now, so there's no long-lived
agent process to report on.
"""

from __future__ import annotations

from central_mcp.registry import load_registry


def render() -> str:
    projects = load_registry()
    if not projects:
        return (
            "## central-mcp\n\n"
            "_(registry is empty — add a project with `central-mcp add NAME PATH --agent claude` "
            "or ask the orchestrator to call `add_project` for you)_"
        )
    lines = ["## central-mcp", "", f"_{len(projects)} project(s) registered_", ""]
    for p in projects:
        tags = f" [{', '.join(p.tags)}]" if p.tags else ""
        desc = f" — {p.description}" if p.description else ""
        lines.append(f"- **{p.name}** (`{p.agent}`) — `{p.path}`{desc}{tags}")
    lines += [
        "",
        "MCP tools: `list_projects`, `project_status`, `dispatch_query`, "
        "`add_project`, `remove_project`.",
        "",
        "dispatch_query runs the agent non-interactively in the project's cwd "
        "and returns its full stdout as `output`.",
    ]
    return "\n".join(lines)


def main() -> int:
    print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
