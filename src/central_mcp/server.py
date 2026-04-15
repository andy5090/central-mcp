from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from central_mcp import layout, paths, tmux
from central_mcp.adapters import get_adapter, has_history
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

When the user wants to add a new project to the hub ("add ~/Projects/foo",
"track this repo too"), call add_project directly. DO NOT tell the user
to run `central-mcp add` in a shell — the in-agent flow is the preferred
UX, and add_project auto-boots the tmux pane. Pick a sensible agent
default (claude if unsure) and mention the choice in your reply.

`dispatch_query` waits for the sub-agent to finish responding by default
(wait_for_idle=true) and returns a `tail` field with the scrubbed pane
output. Read that tail and SUMMARIZE or QUOTE the result back to the
user — do NOT claim the work is done without checking the tail, and do
NOT call fetch_logs for the same information right after (dispatch's
own return value already contains it). If `timed_out` is true, tell the
user the agent was still working when the watchdog fired; if
`activity_seen` is false, the agent never produced output and you
should report that too.
"""

mcp = FastMCP("central-mcp", instructions=_MCP_INSTRUCTIONS)

def _log_root() -> Path:
    return paths.log_root()
_logging_enabled: set[str] = set()

_SHELLS = {"zsh", "bash", "fish", "sh", "dash"}
# Seconds to give a freshly-launched agent CLI to render its welcome banner
# and start accepting keystrokes before we begin sending prompts. tmux's
# pane_current_command is unreliable here (claude/codex run as node children
# of the login shell and don't swap the foreground process), so we fall back
# to a small fixed delay on first boot only.
_FIRST_BOOT_SETTLE_SEC = 1.5


def _ensure_pane_up(project: Project) -> dict[str, Any] | None:
    """Idempotently ensure the project's tmux pane is alive with its agent.

    Three cases, in order:
      1. Pane already exists — no-op.
      2. Session exists but this pane doesn't — split-window (or new-window)
         into the registry-declared window, then launch the agent.
      3. No session at all — cold boot the full layout via ensure_session,
         which handles all registered projects at once.

    Used by every mutating tool (dispatch_query, start_project, add_project)
    so callers never need to run `central-mcp up` manually. Returns None on
    success, or an error dict ready to return from an MCP tool.
    """
    target = project.tmux.target
    if tmux.pane_exists(target):
        return None

    session = project.tmux.session
    window = project.tmux.window
    window_target = f"{session}:{window}"

    if tmux.has_session(session):
        if tmux.pane_exists(window_target):
            r = tmux.split_window(window_target, project.path)
            if not r.ok:
                return {
                    "ok": False,
                    "error": f"split-window {window_target} failed: {r.stderr.strip()}",
                }
            tmux.select_layout(window_target, "tiled")
        else:
            r = tmux.new_window(session, window, project.path)
            if not r.ok:
                return {
                    "ok": False,
                    "error": f"new-window {session}:{window} failed: {r.stderr.strip()}",
                }

        if not tmux.pane_exists(target):
            return {
                "ok": False,
                "error": (
                    f"pane {target} still missing after split — registry pane index "
                    f"(pane={project.tmux.pane}) disagrees with tmux creation order"
                ),
            }

        adapter = get_adapter(project.agent)
        cmd = adapter.launch_command(resume=has_history(project.agent, project.path))
        if cmd:
            tmux.send_keys(target, cmd, enter=True)
            time.sleep(_FIRST_BOOT_SETTLE_SEC)
        return None

    _, messages = layout.ensure_session()
    if not tmux.pane_exists(target):
        detail = "; ".join(messages) if messages else "unknown failure"
        return {
            "ok": False,
            "error": f"pane {target} still missing after ensure_session: {detail}",
        }
    if get_adapter(project.agent).launch:
        time.sleep(_FIRST_BOOT_SETTLE_SEC)
    return None


def _ensure_logging(project: Project) -> None:
    target = project.tmux.target
    if target in _logging_enabled:
        return
    log_path = paths.project_log_path(project.name)
    r = tmux.pipe_pane_to_file(target, log_path)
    if r.ok:
        _logging_enabled.add(target)


def _require_project(name: str) -> tuple[Project | None, dict[str, Any] | None]:
    project = find_project(name)
    if project is None:
        return None, {"ok": False, "error": f"unknown project: {name}"}
    return project, None


def _log_path(project: Project) -> Path:
    return paths.project_log_path(project.name)


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
    wait_for_idle: bool = True,
    idle_seconds: float = 3.0,
    initial_wait: float = 8.0,
    timeout: float = 180.0,
    tail_lines: int = 80,
) -> dict[str, Any]:
    """Send a prompt into the project's tmux pane and (by default) wait
    for the agent to finish responding, then return the resulting tail.

    Flow:
      1. Boot the pane if needed, then send the prompt as keystrokes.
      2. If `wait_for_idle` (default True), watch the project's pane log:
         - Phase A (initial_wait seconds): wait for any byte to be written,
           so we don't mistake a still-warming-up agent for "done".
         - Phase B: wait until the log has not been touched for
           `idle_seconds`, meaning the agent finished writing.
         - Hard cap at `timeout` seconds end-to-end.
      3. Read the last `tail_lines` lines of the pane log, scrubbed,
         and return them so the orchestrator can quote or summarize the
         agent's response without calling fetch_logs separately.

    Set `wait_for_idle=False` for fire-and-forget behavior (old semantics).
    Guards against copy-mode; override with `force=True`.
    """
    import time as _time

    project, err = _require_project(name)
    if err:
        return err
    boot_err = _ensure_pane_up(project)
    if boot_err:
        return boot_err
    target = project.tmux.target
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
    if not result.ok:
        return {"ok": False, "target": target, "stderr": result.stderr}

    response: dict[str, Any] = {"ok": True, "target": target}
    if not wait_for_idle:
        return response

    log_path = _log_path(project)
    waited, timed_out, activity_seen = _wait_for_response(
        log_path,
        idle_seconds=idle_seconds,
        initial_wait=initial_wait,
        timeout=timeout,
    )

    tail_text = ""
    if log_path.exists():
        raw = log_path.read_text(errors="replace")
        tail_text = "\n".join(raw.splitlines()[-tail_lines:])
        tail_text = scrub(tail_text, ansi=True, secrets=True)

    response.update(
        {
            "waited_seconds": round(waited, 1),
            "timed_out": timed_out,
            "activity_seen": activity_seen,
            "tail": tail_text,
        }
    )
    return response


def _wait_for_response(
    log_path: Path,
    *,
    idle_seconds: float,
    initial_wait: float,
    timeout: float,
    poll_interval: float = 0.4,
) -> tuple[float, bool, bool]:
    """Two-phase poll on `log_path`'s mtime.

    Returns `(elapsed, timed_out, activity_seen)`:
      * activity_seen = False means phase A timed out — the agent never
        wrote anything after the prompt was sent.
      * timed_out = True means the overall deadline fired in either phase.
    """
    import time as _t

    def _mtime() -> float | None:
        try:
            return log_path.stat().st_mtime
        except FileNotFoundError:
            return None

    start = _t.time()
    baseline = _mtime()

    # Phase A — wait for any activity.
    phase_a_deadline = start + initial_wait
    activity_seen = False
    while _t.time() < phase_a_deadline:
        if _t.time() - start >= timeout:
            return _t.time() - start, True, False
        current = _mtime()
        if current is not None and current != baseline:
            activity_seen = True
            break
        _t.sleep(poll_interval)
    if not activity_seen:
        return _t.time() - start, False, False

    # Phase B — wait for idle.
    last_mtime = _mtime()
    last_change = _t.time()
    while True:
        now = _t.time()
        if now - start >= timeout:
            return now - start, True, True
        current = _mtime()
        if current is not None and current != last_mtime:
            last_mtime = current
            last_change = now
        elif now - last_change >= idle_seconds:
            return now - start, False, True
        _t.sleep(poll_interval)


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
def start_project(name: str, resume: bool = True) -> dict[str, Any]:
    """Ensure the project's pane is up and its agent CLI is running.

    Idempotent. Creates the tmux layout on first call (same as lazy-boot
    from dispatch_query). If an agent is already running in the pane,
    returns a no-op success. `resume=True` (default) uses the adapter's
    resume command when prior session history for the project's cwd is
    detectable; pass `resume=False` to force a fresh launch.
    """
    project, err = _require_project(name)
    if err:
        return err
    boot_err = _ensure_pane_up(project)
    if boot_err:
        return boot_err
    target = project.tmux.target

    current = tmux.pane_current_command(target)
    if current and current not in _SHELLS:
        return {
            "ok": True,
            "target": target,
            "already_running": current,
            "note": "pane already has an agent running; no-op",
        }

    adapter = get_adapter(project.agent)
    use_resume = resume and has_history(project.agent, project.path)
    cmd = adapter.launch_command(resume=use_resume)
    if not cmd:
        return {"ok": True, "note": f"adapter '{project.agent}' has no launch command (shell)"}

    _ensure_logging(project)
    r = tmux.send_keys(target, cmd, enter=True)
    return {
        "ok": r.ok,
        "target": target,
        "launched": cmd,
        "resumed": use_resume,
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
    start: bool = True,
) -> dict[str, Any]:
    """Append a project to registry.yaml and immediately boot its pane + agent.

    The tmux layout is updated in place: if the target session is already
    running, a new pane is split into the projects window; otherwise the
    full layout is cold-booted. The agent CLI resumes from prior history
    when available. Pass `start=False` to only update the registry.
    """
    try:
        proj = _registry_add(
            name=name, path_=path, agent=agent, session=session,
            window=window, pane=pane, description=description, tags=tags,
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    result: dict[str, Any] = {"ok": True, "project": proj.to_dict()}
    if start:
        boot_err = _ensure_pane_up(proj)
        if boot_err:
            result["started"] = False
            result["boot_warning"] = boot_err.get("error")
        else:
            result["started"] = True
    return result


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
