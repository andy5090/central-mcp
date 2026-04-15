"""Registry-driven tmux layout bootstrap.

Creates a single tmux session with:
  - window "hub"      for the orchestrator
  - window "projects" with one pane per project in registry.yaml

On first creation (not rerun), each project pane auto-launches its configured
agent CLI via the corresponding adapter. Opt out with CENTRAL_MCP_AUTOSTART=0.
Reruns never re-launch: ensure_session bails out if the session already exists.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from central_mcp import paths, tmux
from central_mcp.adapters import get_adapter, has_history
from central_mcp.registry import Project, load_registry, projects_by_session

HUB_SESSION = "central"
HUB_WINDOW = "hub"
PROJECTS_WINDOW = "projects"

# Hub pane layout. Override with CENTRAL_HUB_SPLIT=horizontal|vertical|none.
#   horizontal → left: orchestrator, right: log tail (default)
#   vertical   → top:  orchestrator, bottom: log tail
#   none       → single pane, no auto log tail
_SPLIT_ENV = "CENTRAL_HUB_SPLIT"
_SPLIT_ALIASES = {
    "horizontal": "-h", "h": "-h", "lr": "-h", "left-right": "-h",
    "vertical": "-v", "v": "-v", "tb": "-v", "top-bottom": "-v",
}

# Auto-launch the configured agent in each project pane when the session
# is first created. Set CENTRAL_MCP_AUTOSTART=0 to opt out.
_AUTOSTART_ENV = "CENTRAL_MCP_AUTOSTART"


def _autostart_enabled() -> bool:
    return os.environ.get(_AUTOSTART_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def ensure_session(root: Path | None = None) -> tuple[bool, list[str]]:
    """Idempotently bring up every session referenced by the registry.

    `root` is the initial cwd for the hub window. When omitted, we use
    `paths.central_mcp_home()` — the launch directory where the
    orchestrator preamble lives, so agents spawned there see CLAUDE.md /
    AGENTS.md / .claude/settings.json automatically.

    The session literally named 'central' (HUB_SESSION) gets a 'hub' window
    with auto-split log tail. Other sessions only get a 'projects' window
    with one pane per project — no hub. This lets users distribute projects
    across multiple tmux sessions (e.g. per machine, per client) while
    keeping a single orchestrator-friendly hub.
    """
    if root is None:
        root = paths.central_mcp_home()
        root.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    by_session = projects_by_session()
    # Always create the hub session even if no project lives in it.
    by_session.setdefault(HUB_SESSION, [])

    any_created = False
    for session_name, projects in by_session.items():
        created = _ensure_one_session(session_name, projects, root, messages)
        any_created = any_created or created

    return any_created, messages


def _ensure_one_session(
    session_name: str,
    projects: list[Project],
    root: Path,
    messages: list[str],
) -> bool:
    if tmux.has_session(session_name):
        messages.append(f"session '{session_name}' already exists — leaving as-is")
        return False

    is_hub = session_name == HUB_SESSION
    initial_window = HUB_WINDOW if is_hub else PROJECTS_WINDOW
    initial_cwd = str(root) if is_hub else projects[0].path if projects else str(root)

    # Hub session's first pane is always a shell (user's orchestrator seat);
    # non-hub sessions' first pane is projects[0], which should auto-start
    # if autostart is enabled.
    initial_cmd = None
    if not is_hub and projects and _autostart_enabled():
        initial_cmd = _agent_pane_command(projects[0])

    r = tmux.new_session(session_name, initial_window, initial_cwd, command=initial_cmd)
    if not r.ok:
        messages.append(f"new-session {session_name} failed: {r.stderr.strip()}")
        return False
    messages.append(f"created session '{session_name}' with window '{initial_window}'")

    if is_hub:
        _split_hub_for_logs(root, load_registry(), messages)
        if projects:
            _build_projects_window(session_name, projects, messages)
        tmux._run(["select-window", "-t", f"{session_name}:{HUB_WINDOW}"])
    else:
        rest = projects[1:]
        target = f"{session_name}:{PROJECTS_WINDOW}"
        messages.append(f"{session_name}:{PROJECTS_WINDOW}.0 -> {projects[0].name}{_launch_suffix(projects[0])}")
        for i, p in enumerate(rest, start=1):
            cmd = _agent_pane_command(p) if _autostart_enabled() else None
            r = tmux.split_window(target, p.path, command=cmd)
            if r.ok:
                messages.append(f"{session_name}:{PROJECTS_WINDOW}.{i} -> {p.name}{_launch_suffix(p)}")
        if rest:
            tmux.select_layout(target, "tiled")
        _assign_pane_indices(projects)

    return True


def _agent_pane_command(p: Project) -> str | None:
    """Build the shell command that should be the pane's initial exec.

    Wraps the adapter launch command in `sh -c '<cmd>; exec $SHELL'` so
    the pane falls back to an interactive shell if the agent exits or
    fails, instead of the pane closing. Returns None for the `shell`
    adapter (no launch wanted).
    """
    adapter = get_adapter(p.agent)
    use_resume = has_history(p.agent, p.path)
    cmd = adapter.launch_command(resume=use_resume)
    if not cmd:
        return None
    return f"sh -c '{cmd}; exec $SHELL'"


def _launch_suffix(p: Project) -> str:
    if not _autostart_enabled():
        return ""
    adapter = get_adapter(p.agent)
    cmd = adapter.launch_command(resume=has_history(p.agent, p.path))
    return f"  [exec: {cmd}]" if cmd else "  [shell]"


def _build_projects_window(
    session_name: str,
    projects: list[Project],
    messages: list[str],
) -> None:
    first, *rest = projects
    first_cmd = _agent_pane_command(first) if _autostart_enabled() else None
    r = tmux.new_window(session_name, PROJECTS_WINDOW, first.path, command=first_cmd)
    if not r.ok:
        messages.append(f"new-window failed: {r.stderr.strip()}")
        return
    messages.append(f"projects.0 -> {first.name} ({first.path}){_launch_suffix(first)}")

    target = f"{session_name}:{PROJECTS_WINDOW}"
    for i, p in enumerate(rest, start=1):
        cmd = _agent_pane_command(p) if _autostart_enabled() else None
        r = tmux.split_window(target, p.path, command=cmd)
        if not r.ok:
            messages.append(f"split-window for {p.name} failed: {r.stderr.strip()}")
            continue
        messages.append(f"projects.{i} -> {p.name} ({p.path}){_launch_suffix(p)}")

    if rest:
        tmux.select_layout(target, "tiled")

    _assign_pane_indices(projects)


def _split_hub_for_logs(root: Path, projects: list[Project], messages: list[str]) -> None:
    """Split the hub window so the right/bottom pane live-tails all project logs.

    Controlled by CENTRAL_HUB_SPLIT (horizontal|vertical|none). Pre-creates
    empty log files so `tail -F` doesn't spam "file not found" on first run.
    """
    raw = os.environ.get(_SPLIT_ENV, "horizontal").strip().lower()
    if raw in ("none", "off", "no", ""):
        messages.append("hub split: disabled")
        return
    flag = _SPLIT_ALIASES.get(raw)
    if flag is None:
        messages.append(f"hub split: unknown value {raw!r}, falling back to horizontal")
        flag = "-h"

    log_paths: list[str] = []
    for p in projects:
        lp = paths.project_log_path(p.name)
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.touch(exist_ok=True)
        log_paths.append(str(lp))

    if not log_paths:
        tail_cmd = "echo 'no projects registered — nothing to tail'; exec $SHELL"
    else:
        quoted = " ".join(tmux._shquote(p) for p in log_paths)
        tail_cmd = f"tail -F {quoted}"

    hub_target = f"{HUB_SESSION}:{HUB_WINDOW}"
    r = tmux._run([
        "split-window", flag, "-t", hub_target, "-c", str(root), tail_cmd,
    ])
    if not r.ok:
        messages.append(f"hub split failed: {r.stderr.strip()}")
        return

    # Focus back on the orchestrator pane (index 0).
    tmux._run(["select-pane", "-t", f"{hub_target}.0"])
    direction = "left|right" if flag == "-h" else "top|bottom"
    messages.append(f"hub split ({direction}): orchestrator | tail -F {len(log_paths)} log(s)")


def _assign_pane_indices(projects: list[Project]) -> None:
    """Warn if registry pane indices disagree with layout order.

    We don't rewrite registry.yaml automatically — the user owns that file.
    Phase 0: just emit a warning so the user knows to update.
    """
    expected = {p.name: (i, p.tmux.pane) for i, p in enumerate(projects)}
    for name, (layout_idx, registry_idx) in expected.items():
        if layout_idx != registry_idx:
            print(
                f"warning: {name} is pane {layout_idx} in layout "
                f"but registry says {registry_idx}",
                file=sys.stderr,
            )


def main() -> int:
    created, messages = ensure_session()
    for m in messages:
        print(m)
    if created:
        print()
        print(f"Attach with: tmux attach -t {HUB_SESSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
