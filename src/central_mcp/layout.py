"""Registry-driven tmux layout bootstrap.

Creates a single tmux session with:
  - window "hub"      for the orchestrator
  - window "projects" with one pane per project in registry.yaml

Each project pane starts in its project directory. Agent processes are NOT
launched here — users or the `start_project` MCP tool do that — so central-up
is safe to rerun and never clobbers running agents.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from central_mcp import tmux
from central_mcp.registry import Project, load_registry

SESSION = "central"
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


def ensure_session(root: Path) -> tuple[bool, list[str]]:
    """Idempotently bring up the central session. Returns (created, messages)."""
    messages: list[str] = []
    if tmux.has_session(SESSION):
        messages.append(f"session '{SESSION}' already exists — leaving as-is")
        return False, messages

    projects = load_registry()
    if not projects:
        messages.append("registry.yaml has no projects — creating empty session")

    r = tmux.new_session(SESSION, HUB_WINDOW, str(root))
    if not r.ok:
        messages.append(f"new-session failed: {r.stderr.strip()}")
        return False, messages
    messages.append(f"created session '{SESSION}' with window '{HUB_WINDOW}'")

    _split_hub_for_logs(root, projects, messages)

    if projects:
        first, *rest = projects
        r = tmux.new_window(SESSION, PROJECTS_WINDOW, first.path)
        if not r.ok:
            messages.append(f"new-window failed: {r.stderr.strip()}")
            return True, messages
        messages.append(f"projects.0 -> {first.name} ({first.path})")

        target = f"{SESSION}:{PROJECTS_WINDOW}"
        for i, p in enumerate(rest, start=1):
            r = tmux.split_window(target, p.path)
            if not r.ok:
                messages.append(f"split-window for {p.name} failed: {r.stderr.strip()}")
                continue
            messages.append(f"projects.{i} -> {p.name} ({p.path})")

        if rest:
            tmux.select_layout(target, "tiled")

        _assign_pane_indices(projects)

    tmux._run(["select-window", "-t", f"{SESSION}:{HUB_WINDOW}"])
    return True, messages


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
        lp = root / "logs" / p.name / "pane.log"
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.touch(exist_ok=True)
        log_paths.append(str(lp))

    if not log_paths:
        tail_cmd = "echo 'no projects registered — nothing to tail'; exec $SHELL"
    else:
        quoted = " ".join(tmux._shquote(p) for p in log_paths)
        tail_cmd = f"tail -F {quoted}"

    hub_target = f"{SESSION}:{HUB_WINDOW}"
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
    root = Path(__file__).resolve().parents[2]
    created, messages = ensure_session(root)
    for m in messages:
        print(m)
    if created:
        print()
        print(f"Attach with: tmux attach -t {SESSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
