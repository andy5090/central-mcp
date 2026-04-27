#!/usr/bin/env sh
#
# central-mcp installer
# Usage: curl -fsSL https://central-mcp.org/install.sh | sh
#
# Bootstraps `uv` if missing, installs central-mcp from PyPI,
# and runs `central-mcp init` to scaffold ~/.central-mcp/.

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

log()  { printf "${GREEN}▸${RESET} %s\n" "$1"; }
warn() { printf "${YELLOW}!${RESET} %s\n" "$1" >&2; }
err()  { printf "${RED}✗${RESET} %s\n" "$1" >&2; }
sub()  { printf "  ${DIM}%s${RESET}\n" "$1"; }

# 1. Ensure uv is installed.
if ! command -v uv >/dev/null 2>&1; then
  log "Installing uv (Python package manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # uv installs to ~/.local/bin and emits an env file; source it so the
  # rest of this script sees `uv` immediately.
  if [ -f "$HOME/.local/bin/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.local/bin/env"
  fi

  if ! command -v uv >/dev/null 2>&1; then
    err "uv installed but not on PATH yet."
    sub "Add \$HOME/.local/bin to your shell PATH and re-run:"
    sub "  curl -fsSL https://central-mcp.org/install.sh | sh"
    exit 1
  fi
else
  log "uv already installed: $(uv --version 2>/dev/null || echo unknown)"
fi

# 2. Install central-mcp via uv tool (idempotent — `--upgrade` keeps it fresh).
log "Installing central-mcp from PyPI…"
uv tool install --upgrade central-mcp

# 3. One-time scaffold of ~/.central-mcp/ + cmcp alias.
if command -v central-mcp >/dev/null 2>&1; then
  log "Setting up ~/.central-mcp/…"
  central-mcp init || warn "central-mcp init reported a non-zero exit (this is usually OK on re-runs)."
else
  warn "central-mcp binary not on PATH after install."
  sub "Try: uv tool update-shell"
  sub "Then re-run this script."
  exit 1
fi

cat <<EOF

${GREEN}✓${RESET} central-mcp is ready.

  Run:                  ${DIM}cmcp${RESET}        ${DIM}# launch the orchestrator${RESET}
  Or with full name:    ${DIM}central-mcp${RESET}

  Add a project:        ${DIM}cmcp add my-app ~/Projects/my-app --agent claude${RESET}
  List projects:        ${DIM}cmcp list${RESET}
  Live observation:     ${DIM}cmcp up${RESET}

  Docs: https://central-mcp.org/

EOF
