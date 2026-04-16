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
  - dispatch          — run a one-shot agent in the project's cwd.
                        NON-BLOCKING: returns a dispatch_id immediately.
  - check_dispatch    — poll a dispatch (running / complete / error)
  - list_dispatches   — show all active + recently completed dispatches
  - cancel_dispatch   — abort a running dispatch
  - add_project       — register a new project
  - remove_project    — unregister a project

dispatch is NON-BLOCKING. It spawns the agent as a subprocess and
returns a dispatch_id instantly (<100ms). To get the result:

  1. Call dispatch(name, prompt) → returns dispatch_id.
  2. Spawn a BACKGROUND subagent (Agent tool with run_in_background=true
     in Claude Code, or equivalent) to poll check_dispatch(dispatch_id)
     every 3 seconds until status is no longer "running", then report.
  3. Tell the user "dispatched to <project>, I'll report when it's done"
     and CONTINUE the conversation.

IMPORTANT: Every MCP tool response may include a `completed_dispatches`
array with results from previously dispatched work that has finished
since your last call. When you see this field, REPORT those results to
the user immediately — do not ignore them. This is how completions are
delivered even when background polling agents fail to fire.

If the user mentions a project path that is not yet registered
("add ~/Projects/foo"), call add_project yourself; do not tell the user
to drop to a shell.
"""

mcp = FastMCP("central-mcp", instructions=_MCP_INSTRUCTIONS)

# ---------- background dispatch state ----------
_dispatches: dict[str, dict[str, Any]] = {}
_dispatch_lock = threading.Lock()


def _collect_completed() -> list[dict[str, Any]]:
    """Return and mark-as-reported any dispatches that finished since the
    last call. Piggyback these into every MCP tool response so the
    orchestrator learns about completions without explicit polling —
    even if the background poll agent failed or was never spawned.
    """
    results: list[dict[str, Any]] = []
    with _dispatch_lock:
        for entry in _dispatches.values():
            if entry["status"] != "running" and not entry.get("reported"):
                entry["reported"] = True
                results.append({
                    "dispatch_id": entry["id"],
                    "project": entry["project"],
                    "status": entry["status"],
                    **(entry["result"] or {}),
                })
    return results


def _with_completed(response: Any) -> Any:
    """Attach any unreported dispatch completions to the response.

    Works for both dict and list responses. If there are no pending
    completions, the response is returned unchanged.
    """
    completed = _collect_completed()
    if not completed:
        return response
    if isinstance(response, dict):
        response["completed_dispatches"] = completed
    elif isinstance(response, list):
        return {"results": response, "completed_dispatches": completed}
    return response


def _require_project(name: str) -> tuple[Project | None, dict[str, Any] | None]:
    project = find_project(name)
    if project is None:
        return None, {"ok": False, "error": f"unknown project: {name}"}
    return project, None


@mcp.tool()
def list_projects() -> list[dict[str, Any]] | dict[str, Any]:
    """List every project registered in registry.yaml."""
    return _with_completed([p.to_dict() for p in load_registry()])


@mcp.tool()
def project_status(name: str) -> dict[str, Any]:
    """Return the registry entry for one project.

    This is metadata only — the working directory, adapter, description,
    and tags. Dispatch work via dispatch_query to actually hit the agent.
    """
    project, err = _require_project(name)
    if err:
        return err
    return _with_completed({"ok": True, "project": project.to_dict()})


@mcp.tool()
def dispatch(
    name: str,
    prompt: str,
    resume: bool = True,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Dispatch a prompt to the project's agent. NON-BLOCKING.

    Spawns a one-shot subprocess (e.g. `claude -p "..." --continue`) in the
    project's cwd and returns immediately with a dispatch_id (<100ms).
    The subprocess runs in a background thread.

    To get the result, poll `check_dispatch(dispatch_id)` — when status is
    no longer "running", the full output is available. Use `cancel_dispatch`
    to abort, `list_dispatches` to see everything in flight.

    The orchestrator should spawn a background subagent to handle the
    polling and report, so the main conversation stays unblocked.
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
                f"adapter {project.agent!r} has no non-interactive exec mode. "
                "Supported agents for dispatch: claude, codex, gemini, cursor. "
                "If the project was registered with a wrong agent name, call "
                "remove_project then add_project with the correct agent."
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
                stdin=subprocess.DEVNULL,
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
    `dispatch` call. If the agent is `codex`, also adds a trusted-
    directory entry to `~/.codex/config.toml` so `codex exec` doesn't
    refuse to run in that path.
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

    result: dict[str, Any] = {"ok": True, "project": proj.to_dict()}

    # Auto-trust codex directory so `codex exec` works without manual config.
    if agent == "codex":
        from central_mcp.install import ensure_codex_trust
        trust_msg = ensure_codex_trust(path)
        if trust_msg:
            result["codex_trust"] = trust_msg

    return _with_completed(result)


@mcp.tool()
def remove_project(name: str) -> dict[str, Any]:
    """Remove a project from registry.yaml."""
    removed = _registry_remove(name)
    if not removed:
        return {"ok": False, "error": f"project {name!r} not found in registry"}
    return _with_completed({"ok": True, "removed": name})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
