#!/usr/bin/env bash
#
# central-up.sh — thin shell wrapper around central_mcp.layout.
#
# Layout itself is registry-driven: central_mcp.layout reads registry.yaml
# and creates one tmux pane per project. Idempotent — rerunning on an
# existing session is a no-op.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

uv run --directory "$ROOT" python -m central_mcp.layout

echo
echo "Attach with: tmux attach -t central"
