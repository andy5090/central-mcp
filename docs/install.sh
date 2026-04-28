#!/usr/bin/env sh
#
# central-mcp installer
# Usage: curl -fsSL https://central-mcp.org/install.sh | sh
#
# Bootstraps `uv` if missing, installs central-mcp from PyPI,
# and runs `central-mcp init` to scaffold ~/.central-mcp/.

set -e

# Materialize ANSI escapes once so the variables are usable both as
# `printf` format-string substitutions ("${GREEN}…${RESET}") and as
# `printf '%s'` arguments. POSIX `sh` doesn't have `$'\e[…]'` syntax,
# so we go through `printf` to produce real escape characters.
GREEN=$(printf '\033[0;32m')
YELLOW=$(printf '\033[1;33m')
RED=$(printf '\033[0;31m')
DIM=$(printf '\033[2m')
RESET=$(printf '\033[0m')

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
#    Skip silently if the registry is already present — avoids printing
#    the "registry.yaml already exists" error on re-runs of the script.
if ! command -v central-mcp >/dev/null 2>&1; then
  warn "central-mcp binary not on PATH after install."
  sub "Try: uv tool update-shell"
  sub "Then re-run this script."
  exit 1
fi

if [ -f "$HOME/.central-mcp/registry.yaml" ]; then
  log "~/.central-mcp/ already set up — skipping init."
else
  log "Setting up ~/.central-mcp/…"
  central-mcp init || warn "central-mcp init reported a non-zero exit."
fi

# Closing summary — natural-language usage front and center, CLI shown
# only for things you'd run *outside* an orchestrator session (those
# are the ones that benefit from being typed at a shell prompt).
printf '\n%s✓%s central-mcp is ready.\n\n' "$GREEN" "$RESET"

printf '  Launch the orchestrator:\n'
printf '    %scmcp%s          %s(or: central-mcp)%s\n\n' "$DIM" "$RESET" "$DIM" "$RESET"

printf '  Inside the session, just talk naturally — no command syntax:\n'
printf '    %s"Add ~/Projects/my-app to the hub. Use claude as its agent."%s\n' "$DIM" "$RESET"
printf '    %s"List my projects."%s\n' "$DIM" "$RESET"
printf '    %s"Send my-app and api-server the same prompt: tighten the README."%s\n' "$DIM" "$RESET"
printf '    %s"Any updates?"%s\n\n' "$DIM" "$RESET"

printf '  CLI commands you run outside the session:\n'
printf '    %scmcp run --agent codex%s         one-off orchestrator switch\n' "$DIM" "$RESET"
printf '    %scmcp run --pick%s                change the saved default\n' "$DIM" "$RESET"
printf '    %scmcp run --workspace NAME%s      scope this shell to a workspace\n' "$DIM" "$RESET"
printf '    %scmcp workspace use%s             switch active workspace (picker)\n' "$DIM" "$RESET"
printf '    %scmcp up%s                        live observation panes (tmux/zellij)\n' "$DIM" "$RESET"
printf '    %scmcp watch <project>%s           tail one project'"'"'s dispatch stream\n' "$DIM" "$RESET"
printf '    %scmcp upgrade%s                   update central-mcp itself\n\n' "$DIM" "$RESET"

printf '  Docs: https://central-mcp.org/\n\n'
