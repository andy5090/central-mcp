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

from central_mcp import events, paths
from central_mcp.adapters import get_adapter
from central_mcp.adapters.base import VALID_AGENTS, VALID_PERMISSION_MODES
from central_mcp.registry import (
    Project,
    add_project as _registry_add,
    find_project,
    load_registry,
    remove_project as _registry_remove,
    update_project as _registry_update,
)
from central_mcp.scrub import scrub

DEFAULT_PERMISSION_MODE = "bypass"

# How many chars of dispatch stdout to keep on each terminal event so
# orchestration_history / dispatch_history can surface "what came out"
# without re-reading the raw `output` events. We keep the TAIL, not the
# head, because code agents typically deliver their conclusion at the
# end of their response.
_OUTPUT_PREVIEW_LIMIT = 300


def _output_preview(output: str, limit: int = _OUTPUT_PREVIEW_LIMIT) -> str:
    """Compress a dispatch's final stdout into a short tail preview.

    Returns "" for empty / missing output, the full value for short
    outputs, or an ellipsis-prefixed tail for long ones. The caller's
    stdout is already run through `scrub()` so the preview inherits the
    same secret-redaction guarantees.
    """
    if not output:
        return ""
    stripped = output.rstrip()
    if len(stripped) <= limit:
        return stripped
    return "…" + stripped[-limit:]


_MCP_INSTRUCTIONS = """\
You are connected to central-mcp, a multi-project orchestration hub for
coding agents. Each registered project has a coding-agent CLI
(Claude Code, Codex, Gemini, …) associated with it in the registry.

When the user asks anything about "my projects", status, or dispatching
work, call these MCP tools — do not read files or run shell commands
instead:

  - list_projects          — enumerate the registry
  - project_status         — registry info for one project
  - dispatch               — run a one-shot agent in the project's cwd.
                             NON-BLOCKING: returns a dispatch_id immediately.
  - check_dispatch         — poll a dispatch (running / complete / error)
  - list_dispatches        — show all active + recently completed dispatches
  - cancel_dispatch        — abort a running dispatch
  - dispatch_history       — last N dispatches for one project
  - orchestration_history  — portfolio-wide snapshot: in-flight +
                             recent milestones + per-project stats.
                             Use this when the user asks "overall status?"
                             or "how is everything going?" — a single call
                             gives the orchestrator everything it needs to
                             write a multi-project summary. Each recent
                             milestone carries `prompt_preview` (first
                             120 chars of the prompt) and `output_preview`
                             (tail 300 chars of the agent's stdout) so the
                             orchestrator can group by project and show
                             *what was done + what came out of it* without
                             opening per-project logs.
  - add_project            — register a new project
  - remove_project         — unregister a project
  - update_project         — change a project's agent / fallback / permission_mode / etc.

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

Each project has a `permission_mode` controlling how the dispatched
agent handles permission prompts. Valid values:
  - "bypass"     — skip all permission prompts (default for new projects).
                    claude: --dangerously-skip-permissions,
                    codex: --dangerously-bypass-approvals-and-sandbox,
                    gemini: --yolo, droid: --skip-permissions-unsafe,
                    opencode: --dangerously-skip-permissions.
  - "auto"       — claude-only; classifier-reviewed actions
                    (--enable-auto-mode --permission-mode auto).
                    Requires Team/Enterprise/API plan + Sonnet 4.6 or
                    Opus 4.6. Other agents do not support this.
  - "restricted" — no permission-skip flag; agent may fail on operations
                    that would prompt in `-p` mode.

If a dispatch result contains permission-related errors (e.g. "needs
approval", "permission denied", "not allowed"), tell the user and offer
two options:
  1. Re-dispatch with permission_mode="bypass" (updates saved preference)
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _project_history(project: str, n: int) -> list[dict[str, Any]]:
    """Last N complete/error/cancelled records from the project's jsonl.

    Reads `~/.central-mcp/logs/<project>/dispatch.jsonl`, filters to
    terminal events, and joins them with the matching `start` event so
    the record carries both the prompt and the outcome.
    """
    records = _read_jsonl(events.log_path(project))
    if not records:
        return []
    starts_by_id: dict[str, dict[str, Any]] = {}
    terminals: list[dict[str, Any]] = []
    for r in records:
        evt = r.get("event")
        if evt == "start":
            starts_by_id[r.get("id", "")] = r
        elif evt in ("complete", "error", "cancelled"):
            terminals.append(r)
    terminals.sort(key=lambda r: r.get("ts", ""), reverse=True)
    merged: list[dict[str, Any]] = []
    for t in terminals[:n]:
        s = starts_by_id.get(t.get("id", ""), {})
        merged.append({
            "dispatch_id": t.get("id"),
            "project": project,
            "event": t.get("event"),
            "ts": t.get("ts"),
            "ok": t.get("ok", False),
            "exit_code": t.get("exit_code"),
            "duration_sec": t.get("duration_sec"),
            "agent": t.get("agent_used") or s.get("agent"),
            "fallback_used": t.get("fallback_used", False),
            "error": t.get("error"),
            "prompt": s.get("prompt", ""),
            "output_preview": t.get("output_preview", ""),
        })
    return merged


def _timeline_tail(n: int) -> list[dict[str, Any]]:
    """Last N milestones from the global timeline, newest-first."""
    records = _read_jsonl(events.timeline_path())
    records.sort(key=lambda r: r.get("ts", ""), reverse=True)
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
    permission_mode: str | None = None,
    timeout: float = 600.0,
    agent: str | None = None,
    fallback: list[str] | None = None,
) -> dict[str, Any]:
    """Dispatch a prompt to the project's agent. NON-BLOCKING.

    Spawns a one-shot subprocess (e.g. `claude -p "..." --continue`) in the
    project's cwd and returns immediately with a dispatch_id (<100ms).

    **agent** (optional): override the project's registered agent for this
    one dispatch only. Useful for e.g. sending a design-heavy task to a
    different agent without mutating the registry. Registry is unchanged.

    **fallback** (optional): list of agent names to try in order if the
    primary agent exits non-zero (e.g. token/rate limit, crash). If omitted,
    the project's saved `fallback` from the registry is used. Pass an empty
    list `[]` to explicitly disable fallback for this dispatch.

    **permission_mode** controls how the agent handles permission prompts:
      - "bypass"     — skip all prompts (default for new projects)
      - "auto"       — claude-only; classifier-reviewed actions (Sonnet/Opus 4.6 only)
      - "restricted" — no skip flag; agent may fail on operations needing approval
      - None (default): use the project's saved mode, or "bypass" for new projects.
        The resolved value is saved to the registry for future dispatches.
    """
    project, err = _require_project(name)
    if err:
        return err

    # Resolve effective agent chain: primary then fallbacks
    primary_agent = agent or project.agent
    if fallback is None:
        fallback_chain = list(project.fallback or [])
    else:
        fallback_chain = list(fallback)
    chain = [primary_agent] + fallback_chain

    # Resolve permission_mode BEFORE probing — adapters may return
    # different argv per mode, so we must probe with the real value.
    if permission_mode is None:
        permission_mode = project.permission_mode
    if permission_mode is None:
        permission_mode = DEFAULT_PERMISSION_MODE
    if permission_mode not in VALID_PERMISSION_MODES:
        return {
            "ok": False,
            "error": (
                f"invalid permission_mode {permission_mode!r}; "
                f"valid: {sorted(VALID_PERMISSION_MODES)}"
            ),
        }
    # `auto` is claude-only — refuse chains that include a non-claude
    # agent rather than silently downgrading to bypass on fallback.
    if permission_mode == "auto":
        non_claude = [a for a in chain if a != "claude"]
        if non_claude:
            return {
                "ok": False,
                "error": (
                    f"permission_mode='auto' is claude-only; "
                    f"chain contains non-claude agents: {non_claude}. "
                    "Either switch those agents to claude or use "
                    "permission_mode='bypass'/'restricted'."
                ),
            }

    # Save permission_mode to registry whenever it differs from stored
    # value, so the user can flip modes mid-session by passing an
    # explicit value. New projects also get their default persisted here.
    if project.permission_mode != permission_mode:
        _registry_update(project.name, permission_mode=permission_mode)

    # Validate every agent in the chain produces valid argv with the
    # real prompt + resolved mode, so adapters that conditionally
    # return None based on those inputs fail synchronously rather than
    # inside the background thread.
    for a in chain:
        probe_adapter = get_adapter(a)
        probe_argv = probe_adapter.exec_argv(
            prompt, resume=resume, permission_mode=permission_mode,
        )
        if probe_argv is None:
            return {
                "ok": False,
                "error": (
                    f"adapter {a!r} has no non-interactive exec mode "
                    f"(permission_mode={permission_mode!r}). "
                    f"Supported agents for dispatch: {', '.join(sorted(VALID_AGENTS))}."
                ),
            }

    cwd = Path(project.path)
    if not cwd.is_dir():
        return {
            "ok": False,
            "error": f"project cwd {project.path!r} does not exist",
        }

    # Build the initial argv from the primary agent so we can surface the
    # command string in the return value. Fallback attempts re-build argv
    # in the background thread.
    primary_adapter = get_adapter(primary_agent)
    initial_argv = primary_adapter.exec_argv(
        prompt, resume=resume, permission_mode=permission_mode,
    )

    dispatch_id = uuid.uuid4().hex[:8]
    entry: dict[str, Any] = {
        "id": dispatch_id,
        "project": project.name,
        "agent": primary_agent,
        "chain": chain,
        "prompt": prompt,
        "command": " ".join(initial_argv),
        "status": "running",
        "started": time.time(),
        "process": None,
        "result": None,
        "attempts": [],
    }

    def _run_one(agent_name: str) -> dict[str, Any]:
        """Spawn one attempt with a specific agent. Streams stdout/stderr
        line-by-line into the project's event log while buffering them
        for the final MCP response. Returns result dict with keys:
        ok, exit_code, output, stderr, error (optional), timeout (optional).
        """
        adapter = get_adapter(agent_name)
        argv = adapter.exec_argv(
            prompt, resume=resume, permission_mode=permission_mode,
        )
        import os as _os
        env = _os.environ.copy()
        if hasattr(adapter, "exec_env") and adapter.exec_env:
            env.update(adapter.exec_env)
        attempt_started = time.time()

        events.log_event(
            project.name, dispatch_id, "attempt_start",
            agent=agent_name, command=" ".join(argv),
        )

        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=1,  # line-buffered so reader threads see partial output
            )
        except FileNotFoundError:
            events.log_event(
                project.name, dispatch_id, "error",
                agent=agent_name,
                error=f"agent binary {argv[0]!r} not found on PATH",
            )
            return {
                "agent": agent_name,
                "command": " ".join(argv),
                "ok": False,
                "error": f"agent binary {argv[0]!r} not found on PATH",
                "duration_sec": round(time.time() - attempt_started, 1),
            }
        with _dispatch_lock:
            entry["process"] = proc
            entry["agent"] = agent_name

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def _reader(stream: Any, buffer: list[str], stream_name: str) -> None:
            try:
                for line in stream:
                    buffer.append(line)
                    events.log_event(
                        project.name, dispatch_id, "output",
                        agent=agent_name, stream=stream_name,
                        chunk=line.rstrip("\n"),
                    )
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        out_t = threading.Thread(
            target=_reader, args=(proc.stdout, stdout_lines, "stdout"),
            daemon=True, name=f"dispatch-{dispatch_id}-stdout",
        )
        err_t = threading.Thread(
            target=_reader, args=(proc.stderr, stderr_lines, "stderr"),
            daemon=True, name=f"dispatch-{dispatch_id}-stderr",
        )
        out_t.start()
        err_t.start()

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            out_t.join(timeout=1.0)
            err_t.join(timeout=1.0)
            return {
                "agent": agent_name,
                "command": " ".join(argv),
                "ok": False,
                "timeout": True,
                "error": f"timeout after {timeout}s",
                "output": scrub("".join(stdout_lines), ansi=True, secrets=True),
                "stderr": scrub("".join(stderr_lines), ansi=True, secrets=True),
                "duration_sec": round(time.time() - attempt_started, 1),
            }
        out_t.join(timeout=1.0)
        err_t.join(timeout=1.0)
        return {
            "agent": agent_name,
            "command": " ".join(argv),
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": scrub("".join(stdout_lines), ansi=True, secrets=True),
            "stderr": scrub("".join(stderr_lines), ansi=True, secrets=True),
            "duration_sec": round(time.time() - attempt_started, 1),
        }

    def _run_bg() -> None:
        attempts: list[dict[str, Any]] = []
        final_result: dict[str, Any] | None = None
        final_status = "complete"
        try:
            for agent_name in chain:
                # Honor cancellation between attempts so a cancel during
                # attempt N doesn't silently run attempt N+1.
                with _dispatch_lock:
                    if entry.get("cancel_requested"):
                        break
                attempt = _run_one(agent_name)
                attempts.append(attempt)
                with _dispatch_lock:
                    entry["attempts"] = list(attempts)
                if attempt.get("ok"):
                    break
                # Don't fall back on timeout — user probably wants to see it
                # rather than burn their whole fallback chain on a stuck agent.
                if attempt.get("timeout"):
                    break

            with _dispatch_lock:
                was_cancelled = bool(entry.get("cancel_requested"))

            if was_cancelled:
                final_status = "cancelled"
                final_result = {
                    "ok": False,
                    "error": "cancelled by orchestrator",
                    "agent_used": attempts[-1].get("agent") if attempts else primary_agent,
                    "duration_sec": round(time.time() - entry["started"], 1),
                    "attempts": attempts,
                    "fallback_used": len(attempts) > 1,
                }
            elif not attempts:
                final_status = "error"
                final_result = {
                    "ok": False,
                    "error": "no attempts ran (chain was empty)",
                    "attempts": attempts,
                }
            else:
                last = attempts[-1]
                final_result = {
                    "ok": last.get("ok", False),
                    "agent_used": last.get("agent"),
                    "exit_code": last.get("exit_code"),
                    "output": last.get("output", ""),
                    "stderr": last.get("stderr", ""),
                    "error": last.get("error"),
                    "duration_sec": round(time.time() - entry["started"], 1),
                    "attempts": attempts,
                    "fallback_used": len(attempts) > 1,
                }
                if last.get("timeout"):
                    final_status = "timeout"
        except Exception as exc:
            final_status = "error"
            final_result = {
                "ok": False,
                "error": str(exc),
                "attempts": attempts,
            }

        with _dispatch_lock:
            entry["status"] = final_status
            entry["result"] = final_result

        # Condense the final stdout into a tail preview that rides on
        # both the terminal event and the timeline milestone. This is
        # what dispatch_history / orchestration_history later surface
        # as "what came out of this dispatch" — without forcing the
        # orchestrator to re-read every `output` event from the jsonl.
        output_preview = _output_preview((final_result or {}).get("output", ""))

        # Emit terminal event for the watch log.
        events.log_event(
            project.name, dispatch_id,
            "error" if final_status == "error" else "complete",
            status=final_status,
            ok=bool(final_result and final_result.get("ok")),
            exit_code=final_result.get("exit_code") if final_result else None,
            agent_used=final_result.get("agent_used") if final_result else None,
            duration_sec=final_result.get("duration_sec") if final_result else None,
            fallback_used=bool(final_result and final_result.get("fallback_used")),
            error=final_result.get("error") if final_result else None,
            output_preview=output_preview,
        )

        # Append a compact milestone to the global timeline so portfolio-
        # level summaries (`orchestration_history`) don't have to fan out
        # across per-project log files.
        events.log_timeline(
            dispatch_id, project.name,
            "error" if final_status == "error" else final_status,
            agent=(final_result.get("agent_used") if final_result else None) or entry["agent"],
            ok=bool(final_result and final_result.get("ok")),
            exit_code=final_result.get("exit_code") if final_result else None,
            duration_sec=final_result.get("duration_sec") if final_result else None,
            fallback_used=bool(final_result and final_result.get("fallback_used")),
            prompt_preview=(entry.get("prompt") or "")[:120],
            output_preview=output_preview,
        )

    with _dispatch_lock:
        _dispatches[dispatch_id] = entry

    events.log_event(
        project.name, dispatch_id, "start",
        agent=primary_agent, chain=chain,
        prompt=prompt, command=" ".join(initial_argv), cwd=str(cwd),
    )
    events.log_timeline(
        dispatch_id, project.name, "dispatched",
        agent=primary_agent, chain=chain,
        prompt_preview=prompt[:120],
    )

    t = threading.Thread(target=_run_bg, daemon=True, name=f"dispatch-{dispatch_id}")
    t.start()

    return {
        "ok": True,
        "dispatch_id": dispatch_id,
        "project": project.name,
        "agent": primary_agent,
        "chain": chain,
        "command": " ".join(initial_argv),
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
    """Abort a running background dispatch. No-op if already finished.

    Sets a cancel flag so `_run_bg` stops before the next fallback
    attempt, then terminates the current subprocess. The background
    thread finalizes the status to "cancelled".
    """
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
        entry["cancel_requested"] = True
        proc = entry.get("process")
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
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
    if agent not in VALID_AGENTS:
        return {
            "ok": False,
            "error": (
                f"unknown agent {agent!r}. "
                f"Valid agents: {', '.join(sorted(VALID_AGENTS))}."
            ),
        }
    adapter = get_adapter(agent)
    if not adapter.has_exec:
        return {
            "ok": False,
            "error": f"agent {agent!r} has no non-interactive dispatch mode.",
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
def update_project(
    name: str,
    agent: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    permission_mode: str | None = None,
    fallback: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing project's fields. Omitted args stay unchanged.

    Use this to permanently change a project's primary agent, edit its
    description/tags, flip its permission_mode preference, or set a
    fallback chain of agents to try when the primary fails (e.g. token
    limits hit).

    Agent names in `agent` and `fallback` are validated. `permission_mode`
    must be one of "bypass", "auto", "restricted". If any value is
    invalid the registry is not touched.
    """
    if agent is not None:
        if agent not in VALID_AGENTS:
            return {
                "ok": False,
                "error": (
                    f"unknown agent {agent!r}. "
                    f"Valid: {', '.join(sorted(VALID_AGENTS))}."
                ),
            }
        if not get_adapter(agent).has_exec:
            return {
                "ok": False,
                "error": f"agent {agent!r} has no non-interactive exec mode.",
            }

    if fallback is not None:
        for a in fallback:
            if a not in VALID_AGENTS:
                return {
                    "ok": False,
                    "error": (
                        f"unknown agent {a!r} in fallback. "
                        f"Valid: {', '.join(sorted(VALID_AGENTS))}."
                    ),
                }
            if not get_adapter(a).has_exec:
                return {
                    "ok": False,
                    "error": f"agent {a!r} in fallback has no non-interactive exec mode.",
                }

    if permission_mode is not None and permission_mode not in VALID_PERMISSION_MODES:
        return {
            "ok": False,
            "error": (
                f"invalid permission_mode {permission_mode!r}; "
                f"valid: {sorted(VALID_PERMISSION_MODES)}"
            ),
        }

    updated = _registry_update(
        name,
        agent=agent,
        description=description,
        tags=tags,
        permission_mode=permission_mode,
        fallback=fallback,
    )
    if updated is None:
        return {"ok": False, "error": f"project {name!r} not found in registry"}

    result: dict[str, Any] = {"ok": True, "project": updated.to_dict()}

    # If agent switched to codex, make sure its cwd is in codex's trust list.
    if agent == "codex":
        from central_mcp.install import ensure_codex_trust
        trust_msg = ensure_codex_trust(updated.path)
        if trust_msg:
            result["codex_trust"] = trust_msg

    return _with_completed(result)


@mcp.tool()
def dispatch_history(
    name: str,
    n: int = 10,
) -> dict[str, Any]:
    """Return the last N completed/failed/cancelled dispatches for one project.

    Reads `~/.central-mcp/logs/<project>/dispatch.jsonl` and extracts
    terminal events (merged with their matching `start` so each record
    carries both the prompt and the outcome). For a cross-project
    portfolio summary, use `orchestration_history` instead.
    """
    project, err = _require_project(name)
    if err:
        return err
    records = _project_history(project.name, n)
    return _with_completed({
        "ok": True,
        "project": project.name,
        "count": len(records),
        "records": records,
    })


@mcp.tool()
def orchestration_history(
    n: int = 20,
    window_minutes: int | None = None,
) -> dict[str, Any]:
    """Portfolio-wide snapshot: in-flight dispatches + recent milestones + per-project stats.

    Answers "how is everything going?" without per-project polling.
    Pulls:
      - `in_flight`: currently running dispatches (from memory)
      - `recent`: last N timeline milestones (dispatched/complete/
        error/cancelled) across all projects, newest first
      - `per_project`: counts of succeeded/failed/in-flight per project
        within `window_minutes` (or all-time if not given)
      - `registered_projects`: registry snapshot for context
    """
    timeline = _read_jsonl(events.timeline_path())
    timeline.sort(key=lambda r: r.get("ts", ""), reverse=True)

    if window_minutes is not None:
        cutoff_dt = datetime.now(timezone.utc).timestamp() - window_minutes * 60
        def _in_window(r: dict[str, Any]) -> bool:
            try:
                ts = datetime.fromisoformat(r.get("ts", "").replace("Z", "+00:00"))
                return ts.timestamp() >= cutoff_dt
            except Exception:
                return True  # don't lose records on bad ts
        filtered = [r for r in timeline if _in_window(r)]
    else:
        filtered = timeline

    recent = filtered[:n]

    # Per-project aggregation (count terminal events by outcome).
    per_project: dict[str, dict[str, int]] = {}
    last_ts_by_project: dict[str, str] = {}
    for r in filtered:
        proj = r.get("project", "?")
        stats = per_project.setdefault(proj, {
            "dispatched": 0, "succeeded": 0, "failed": 0, "cancelled": 0,
        })
        evt = r.get("event")
        if evt == "dispatched":
            stats["dispatched"] += 1
        elif evt == "complete":
            if r.get("ok"):
                stats["succeeded"] += 1
            else:
                stats["failed"] += 1
        elif evt == "error":
            stats["failed"] += 1
        elif evt == "cancelled":
            stats["cancelled"] += 1
        ts = r.get("ts", "")
        if ts > last_ts_by_project.get(proj, ""):
            last_ts_by_project[proj] = ts
    for proj, last_ts in last_ts_by_project.items():
        per_project[proj]["last_ts"] = last_ts  # type: ignore[assignment]

    with _dispatch_lock:
        in_flight = [
            {
                "dispatch_id": e["id"],
                "project": e["project"],
                "agent": e["agent"],
                "elapsed_sec": round(time.time() - e["started"], 1),
                "prompt_preview": (e.get("prompt") or "")[:120],
            }
            for e in _dispatches.values()
            if e["status"] == "running"
        ]

    registered = [p.to_dict() for p in load_registry()]

    return _with_completed({
        "ok": True,
        "window_minutes": window_minutes,
        "in_flight": in_flight,
        "recent": recent,
        "per_project": per_project,
        "registered_projects": registered,
    })


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
