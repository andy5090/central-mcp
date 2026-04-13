#!/usr/bin/env bash
#
# central-up.sh — bring up a tmux layout for central-mcp.
#
# Phase 0: hardcoded minimal layout.
#   window "hub"      — one pane for the orchestrator (Claude Code / Codex / ...)
#   window "projects" — one pane per project from registry.yaml (currently: gluecut-dawg)
#
# This is intentionally simple. Replace with a registry-driven generator once
# the schema stabilizes.

set -euo pipefail

SESSION="central"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' already exists — attaching."
    tmux attach -t "$SESSION"
    exit 0
fi

# Window 1: orchestrator hub (starts in project-central root)
tmux new-session -d -s "$SESSION" -n "hub" -c "$ROOT"

# Window 2: projects — pane 0 = gluecut-dawg
tmux new-window -t "$SESSION" -n "projects" -c "$HOME/Projects/gluecut-dawg"

# Come back to the hub window on attach.
tmux select-window -t "$SESSION:hub"

echo "Session '$SESSION' created."
echo "  hub      — launch your orchestrator here: claude | codex | cursor-agent ..."
echo "  projects — pane 0: gluecut-dawg (launch the project's agent here)"
echo
echo "Attach with: tmux attach -t $SESSION"
