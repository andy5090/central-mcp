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

import json
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
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

If a dispatch result contains permission-related errors (e.g. "needs
approval", "permission denied", "not allowed"), tell the user and offer
two options:
  1. Re-dispatch with bypass=true (updates saved preference permanently)
  2. Use `central-mcp up` to open a tmux observation session where
     the agent runs interactively and the user can approve manually

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


def _history_dir() -> Path:
    return paths.central_mcp_home() / "history"


def _append_history(project: str, record: dict[str, Any]) -> None:
    """Append a dispatch record to the project's history JSONL file."""
    hdir = _history_dir()
    hdir.mkdir(parents=True, exist_ok=True)
    fpath = hdir / f"{project}.jsonl"
    with fpath.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_history(project: str | None = None, n: int = 10) -> list[dict[str, Any]]:
    """Read the last N dispatch records. If project is None, read across all."""
    hdir = _history_dir()
    if not hdir.exists():
        return []

    files = [hdir / f"{project}.jsonl"] if project else sorted(hdir.glob("*.jsonl"))
    records: list[dict[str, Any]] = []
    for fpath in files:
        if not fpath.exists():
            continue
        for line in fpath.read_text(errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    # Sort by timestamp descending, take last N
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records[:n]


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
    bypass: bool | None = None,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Dispatch a prompt to the project's agent. NON-BLOCKING.

    Spawns a one-shot subprocess (e.g. `claude -p "..." --continue`) in the
    project's cwd and returns immediately with a dispatch_id (<100ms).

    **bypass** controls whether the agent runs with permission-skip flags:
      - `true`: skip all permission prompts (--dangerously-skip-permissions etc.)
      - `false`: run without bypass (agent may fail if it needs approvals)
      - `null` (default): use the project's saved bypass preference from the
        registry. If no preference is saved yet (first dispatch), the server
        returns a `needs_bypass_decision` response instead of dispatching —
        the orchestrator should ask the user and re-call with an explicit value.
        The choice is then saved to the registry for future dispatches.
    """
    project, err = _require_project(name)
    if err:
        return err

    # Resolve bypass: explicit param > registry saved > ask user
    if bypass is None:
        bypass = project.bypass
    if bypass is None:
        return {
            "ok": False,
            "needs_bypass_decision": True,
            "project": project.name,
            "agent": project.agent,
            "error": (
                f"First dispatch to '{project.name}' — bypass mode not yet decided. "
                "Ask the user: should this agent run with full permissions "
                "(bypass=true, skips all approval prompts) or restricted "
                "(bypass=false, may fail on operations needing approval)? "
                "Then call dispatch again with bypass=true or bypass=false. "
                "Note: if bypass=false and the agent needs approvals, the user "
                "can run `central-mcp up` and interact with the agent directly "
                "in a tmux pane where manual approval is possible."
            ),
        }

    # Save bypass preference to registry — always when explicitly passed,
    # so the user can flip from false→true (or vice versa) mid-session
    # by calling dispatch with an explicit bypass value.
    if project.bypass != bypass:
        from central_mcp.registry import update_project_bypass
        update_project_bypass(project.name, bypass)

    adapter = get_adapter(project.agent)
    argv = adapter.exec_argv(prompt, resume=resume, bypass=bypass)
    if argv is None:
        return {
            "ok": False,
            "error": (
                f"adapter {project.agent!r} has no non-interactive exec mode. "
                "Supported agents for dispatch: claude, codex, gemini, droid, amp. "
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
        "prompt": prompt,
        "command": " ".join(argv),
        "status": "running",
        "started": time.time(),
        "process": None,
        "result": None,
    }

    def _run_bg() -> None:
        try:
            # Merge adapter-specific env vars if present
            # into the current environment so the subprocess inherits PATH etc.
            import os as _os
            env = _os.environ.copy()
            if hasattr(adapter, "exec_env") and adapter.exec_env:
                env.update(adapter.exec_env)

            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
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
                result_data = {
                    "ok": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "output": scrub(stdout, ansi=True, secrets=True),
                    "stderr": scrub(stderr, ansi=True, secrets=True),
                    "duration_sec": round(time.time() - entry["started"], 1),
                }
                entry["result"] = result_data
            # Write to persistent history (outside lock)
            _append_history(entry["project"], {
                "dispatch_id": entry["id"],
                "project": entry["project"],
                "agent": entry["agent"],
                "prompt": entry.get("prompt", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": result_data["ok"],
                "exit_code": result_data.get("exit_code"),
                "duration_sec": result_data.get("duration_sec"),
                "output_preview": result_data.get("output", "")[:500],
            })
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
    # Validate agent name at registration time so users don't hit
    # "no exec mode" errors only when they first try to dispatch.
    from central_mcp.adapters.base import VALID_AGENTS
    adapter = get_adapter(agent)
    if agent not in VALID_AGENTS:
        return {
            "ok": False,
            "error": (
                f"unknown agent {agent!r}. "
                f"Valid agents: {', '.join(sorted(VALID_AGENTS - {'shell'}))}. "
                "Use 'shell' for registry-only projects (no dispatch)."
            ),
        }
    if not adapter.has_exec and agent != "shell":
        return {
            "ok": False,
            "error": (
                f"agent {agent!r} has no non-interactive dispatch mode. "
                f"Supported agents for dispatch: {', '.join(sorted(a for a in VALID_AGENTS if get_adapter(a).has_exec))}."
            ),
        }

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


@mcp.tool()
def dispatch_history(
    name: str | None = None,
    n: int = 10,
) -> dict[str, Any]:
    """Return the last N dispatch records from persistent history.

    Pass `name` to filter by project; omit for cross-project history.
    Each record includes: dispatch_id, project, agent, prompt,
    timestamp, ok, exit_code, duration_sec, output_preview (first 500
    chars). History survives server restarts — it's stored on disk at
    ~/.central-mcp/history/<project>.jsonl.
    """
    records = _read_history(project=name, n=n)
    return _with_completed({
        "ok": True,
        "count": len(records),
        "project_filter": name,
        "records": records,
    })


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
