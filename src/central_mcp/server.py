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
import threading
import time
import uuid
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
  - dispatch_query       — run a one-shot non-interactive agent in the
                          project's cwd and return its full stdout (SYNC)
  - dispatch_background  — same but NON-BLOCKING: returns a dispatch_id
  - check_dispatch        — poll a background dispatch (running / done)
  - list_dispatches       — show all active + recently completed dispatches
  - cancel_dispatch       — abort a running background dispatch
  - add_project           — register a new project
  - remove_project        — unregister a project

**PREFERRED DISPATCH PATTERN — use dispatch_background, not dispatch_query:**

dispatch_query blocks the entire conversation until the subprocess
finishes (often 30–120 seconds). During that time the user cannot
type anything. Prefer dispatch_background instead:

  1. Call dispatch_background(name, prompt) — returns immediately with
     a dispatch_id.
  2. Spawn a BACKGROUND subagent (Agent tool with run_in_background=true
     in Claude Code, or equivalent) whose sole job is to poll
     check_dispatch(dispatch_id) every 10 seconds until status is no
     longer "running", then report the result.
  3. Tell the user "dispatched to <project>, I'll report when it's done"
     and CONTINUE the conversation. Accept the next request without
     waiting.

This way the user can fire off requests to multiple projects and keep
talking while each runs. Results arrive asynchronously via the
background subagent.

Use dispatch_query (synchronous) ONLY when the user explicitly says
"wait for the result" or "don't move on until this is done."

If the user mentions a project path that is not yet registered
("add ~/Projects/foo"), call add_project yourself; do not tell the user
to drop to a shell.
"""

mcp = FastMCP("central-mcp", instructions=_MCP_INSTRUCTIONS)

# ---------- background dispatch state ----------
_dispatches: dict[str, dict[str, Any]] = {}
_dispatch_lock = threading.Lock()


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
def dispatch_background(
    name: str,
    prompt: str,
    resume: bool = True,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Like dispatch_query but NON-BLOCKING. Returns immediately with a
    dispatch_id. Use check_dispatch(dispatch_id) to poll for the result.

    Ideal for parallel work: call dispatch_background on multiple projects,
    then iterate with check_dispatch until each completes. Each dispatch is
    an independent subprocess.
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
                "use dispatch_query or dispatch_background with claude/codex/gemini only"
            ),
        }

    cwd = Path(project.path)
    if not cwd.is_dir():
        return {
            "ok": False,
            "error": f"project cwd {project.path!r} does not exist",
        }

    dispatch_id = uuid.uuid4().hex[:8]
    entry: dict[str, Any] = {
        "id": dispatch_id,
        "project": project.name,
        "agent": project.agent,
        "command": " ".join(argv),
        "status": "running",
        "started": time.time(),
        "process": None,
        "result": None,
    }

    def _run_bg() -> None:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with _dispatch_lock:
                entry["process"] = proc
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                with _dispatch_lock:
                    entry["status"] = "timeout"
                    entry["result"] = {
                        "ok": False,
                        "error": f"timeout after {timeout}s",
                        "partial_output": scrub(stdout or "", ansi=True, secrets=True),
                        "partial_stderr": scrub(stderr or "", ansi=True, secrets=True),
                    }
                return

            with _dispatch_lock:
                entry["status"] = "complete"
                entry["result"] = {
                    "ok": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "output": scrub(stdout, ansi=True, secrets=True),
                    "stderr": scrub(stderr, ansi=True, secrets=True),
                    "duration_sec": round(time.time() - entry["started"], 1),
                }
        except FileNotFoundError:
            with _dispatch_lock:
                entry["status"] = "error"
                entry["result"] = {
                    "ok": False,
                    "error": f"agent binary {argv[0]!r} not found on PATH",
                }
        except Exception as exc:
            with _dispatch_lock:
                entry["status"] = "error"
                entry["result"] = {"ok": False, "error": str(exc)}

    with _dispatch_lock:
        _dispatches[dispatch_id] = entry

    t = threading.Thread(target=_run_bg, daemon=True, name=f"dispatch-{dispatch_id}")
    t.start()

    return {
        "ok": True,
        "dispatch_id": dispatch_id,
        "project": project.name,
        "agent": project.agent,
        "command": " ".join(argv),
        "note": "running in background — poll with check_dispatch(dispatch_id)",
    }


@mcp.tool()
def check_dispatch(dispatch_id: str) -> dict[str, Any]:
    """Poll a background dispatch started by dispatch_background.

    Returns `{status: "running", elapsed_sec}` while the subprocess is
    alive, or the full result (same shape as dispatch_query's return
    value) once it has exited.
    """
    with _dispatch_lock:
        entry = _dispatches.get(dispatch_id)
    if entry is None:
        return {"ok": False, "error": f"no dispatch with id {dispatch_id!r}"}
    if entry["status"] == "running":
        return {
            "ok": True,
            "status": "running",
            "dispatch_id": dispatch_id,
            "project": entry["project"],
            "elapsed_sec": round(time.time() - entry["started"], 1),
        }
    return {
        "ok": True,
        "status": entry["status"],
        "dispatch_id": dispatch_id,
        "project": entry["project"],
        **(entry["result"] or {}),
    }


@mcp.tool()
def list_dispatches() -> list[dict[str, Any]]:
    """List all active and recently completed background dispatches."""
    with _dispatch_lock:
        return [
            {
                "dispatch_id": e["id"],
                "project": e["project"],
                "agent": e["agent"],
                "status": e["status"],
                "elapsed_sec": round(time.time() - e["started"], 1),
            }
            for e in _dispatches.values()
        ]


@mcp.tool()
def cancel_dispatch(dispatch_id: str) -> dict[str, Any]:
    """Abort a running background dispatch. No-op if already finished."""
    with _dispatch_lock:
        entry = _dispatches.get(dispatch_id)
    if entry is None:
        return {"ok": False, "error": f"no dispatch with id {dispatch_id!r}"}
    if entry["status"] != "running":
        return {
            "ok": True,
            "note": f"dispatch already {entry['status']}",
            "dispatch_id": dispatch_id,
        }
    proc = entry.get("process")
    if proc is not None:
        proc.terminate()
    with _dispatch_lock:
        entry["status"] = "cancelled"
        entry["result"] = {"ok": False, "error": "cancelled by orchestrator"}
    return {"ok": True, "cancelled": dispatch_id}


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
