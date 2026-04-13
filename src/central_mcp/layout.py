"""Registry-driven tmux layout bootstrap.

Creates a single tmux session with:
  - window "hub"      for the orchestrator
  - window "projects" with one pane per project in registry.yaml

Each project pane starts in its project directory. Agent processes are NOT
launched here — users or the `start_project` MCP tool do that — so central-up
is safe to rerun and never clobbers running agents.
"""

from __future__ import annotations

import sys
from pathlib import Path

from central_mcp import tmux
from central_mcp.registry import Project, load_registry

SESSION = "central"
HUB_WINDOW = "hub"
PROJECTS_WINDOW = "projects"


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
