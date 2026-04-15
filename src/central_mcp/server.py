"""central-mcp MCP server.

Every mutating tool runs through a plain subprocess call — no tmux pane
observation, no pipe-pane scraping, no send-keys. Each dispatch spawns
the configured agent CLI in the project's cwd using its non-interactive
mode (`claude -p --continue`, `codex exec`, `gemini -p`), captures stdout
and stderr, and returns them to the orchestrator over MCP.

An optional tmux "observation" layer exists separately — see
`central_mcp.layout` and the `up` / `down` CLI subcommands. It creates a
single window with one interactive pane per project so humans can peek
at each agent in real time, but that layer is not on any MCP tool's
critical path and can be absent entirely.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from central_mcp import paths
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
coding agents. Each registered project has a coding-agent CLI
(Claude Code, Codex, Gemini, …) associated with it in the registry.

When the user asks anything about "my projects", status, or dispatching
work, call these MCP tools — do not read files or run shell commands
instead:

  - list_projects    — enumerate the registry
  - project_status   — registry info for one project
  - dispatch_query   — run a one-shot non-interactive agent in the
                       project's cwd and return its full stdout
  - add_project      — register a new project
  - remove_project   — unregister a project

dispatch_query is SYNCHRONOUS: it spawns the agent as a subprocess
(for example `claude -p "..." --continue` inside the project directory),
waits for the process to exit, and returns its entire stdout as the
`output` field of the MCP response. READ that output and summarize or
quote it back to the user in the same turn — do not say "dispatched"
and stop. If `ok` is false, report stderr and the exit code.

If the user mentions a project path that is not yet registered
("add ~/Projects/foo"), call add_project yourself; do not tell the user
to drop to a shell.
"""

mcp = FastMCP("central-mcp", instructions=_MCP_INSTRUCTIONS)


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
def project_status(name: str) -> dict[str, Any]:
    """Return the registry entry for one project.

    This is metadata only — the working directory, adapter, description,
    and tags. Dispatch work via dispatch_query to actually hit the agent.
    """
    project, err = _require_project(name)
    if err:
        return err
    return {"ok": True, "project": project.to_dict()}


@mcp.tool()
def dispatch_query(
    name: str,
    prompt: str,
    resume: bool = True,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Run the project's agent non-interactively and return its response.

    Spawns a one-shot subprocess using the adapter's `exec_argv`:
      - claude: `claude -p <prompt> [--continue]`
      - codex:  `codex exec <prompt>`
      - gemini: `gemini -p <prompt>`

    Runs with `cwd` set to the project path so Claude's `--continue`
    picks up the most recent conversation for that directory. Captures
    stdout and stderr, then returns the result to the orchestrator. The
    orchestrator should read `output` and relay it to the user.

    Parameters:
      - name: registry identifier of the target project
      - prompt: the natural-language request for the sub-agent
      - resume: if True (default), resume prior session state when the
                adapter supports it (claude's --continue flag). Set
                False to force a fresh context.
      - timeout: seconds to wait before killing the subprocess
    """
    project, err = _require_project(name)
    if err:
        return err

    adapter = get_adapter(project.agent)
    argv = adapter.exec_argv(prompt, resume=resume)
    if argv is None:
        return {
            "ok": False,
            "error": (
                f"adapter {project.agent!r} has no non-interactive exec mode; "
                "dispatch_query needs an adapter that supports one-shot mode "
                "(claude/codex/gemini)"
            ),
        }

    cwd = Path(project.path)
    if not cwd.is_dir():
        return {
            "ok": False,
            "error": f"project cwd {project.path!r} does not exist or is not a directory",
        }

    started = time.time()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"agent binary {argv[0]!r} not found on PATH",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": f"timeout after {timeout}s",
            "partial_output": scrub(exc.stdout or "", ansi=True, secrets=True),
            "partial_stderr": scrub(exc.stderr or "", ansi=True, secrets=True),
        }

    duration = round(time.time() - started, 1)
    return {
        "ok": completed.returncode == 0,
        "project": project.name,
        "agent": project.agent,
        "exit_code": completed.returncode,
        "duration_sec": duration,
        "output": scrub(completed.stdout, ansi=True, secrets=True),
        "stderr": scrub(completed.stderr, ansi=True, secrets=True),
        "command": " ".join(argv),
    }


@mcp.tool()
def add_project(
    name: str,
    path: str,
    agent: str = "claude",
    description: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Append a project to registry.yaml.

    Registration is immediate. The agent is not spawned until the next
    `dispatch_query` — there is no tmux pane to boot, no background
    process to supervise.
    """
    try:
        proj = _registry_add(
            name=name,
            path_=path,
            agent=agent,
            description=description,
            tags=tags,
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "project": proj.to_dict()}


@mcp.tool()
def remove_project(name: str) -> dict[str, Any]:
    """Remove a project from registry.yaml."""
    removed = _registry_remove(name)
    if not removed:
        return {"ok": False, "error": f"project {name!r} not found in registry"}
    return {"ok": True, "removed": name}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
