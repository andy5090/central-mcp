"""Centralized path resolution for central-mcp.

Every path the package needs — config home, log root, registry fallback,
launch directory — resolves through this module. This is the only layer
that knows about environment variables, `$HOME`, or the current working
directory, so the rest of the code stays easy to test (monkey-patch
these functions in pytest and every consumer follows).

Layout (defaults):
  $CENTRAL_MCP_HOME            → ~/.central-mcp
  $CENTRAL_MCP_HOME/registry.yaml
  $CENTRAL_MCP_HOME/config.toml
  $CENTRAL_MCP_HOME/logs/<project>/pane.log
  $CENTRAL_MCP_HOME/CLAUDE.md
  $CENTRAL_MCP_HOME/AGENTS.md
  $CENTRAL_MCP_HOME/.claude/settings.json

All functions re-read the environment on every call so tests can flip
`CENTRAL_MCP_HOME` between cases without reimporting anything.
"""

from __future__ import annotations

import os
from pathlib import Path


def central_mcp_home() -> Path:
    """Return the user-facing central-mcp directory.

    Resolution order:
      1. `$CENTRAL_MCP_HOME` (explicit override)
      2. `~/.central-mcp`

    The returned path is absolute but MAY NOT EXIST yet — callers that
    need to write should call `central_mcp_home().mkdir(parents=True,
    exist_ok=True)`.
    """
    env = os.environ.get("CENTRAL_MCP_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".central-mcp").resolve()


def registry_path() -> Path:
    """Resolve the registry.yaml path via a three-level cascade.

    1. `$CENTRAL_MCP_REGISTRY` (explicit override)
    2. `./registry.yaml` in the current working directory, if it exists
    3. `<central_mcp_home()>/registry.yaml`
    """
    env = os.environ.get("CENTRAL_MCP_REGISTRY")
    if env:
        return Path(env).expanduser().resolve()
    cwd_candidate = Path.cwd() / "registry.yaml"
    if cwd_candidate.exists():
        return cwd_candidate.resolve()
    return central_mcp_home() / "registry.yaml"


def config_file() -> Path:
    """Path to the orchestrator-preference config file."""
    return central_mcp_home() / "config.toml"


def log_root() -> Path:
    """Root of per-project pane log files."""
    return central_mcp_home() / "logs"


def project_log_path(project_name: str) -> Path:
    """`logs/<project>/pane.log` under the log root."""
    return log_root() / project_name / "pane.log"


def session_info_file() -> Path:
    """Path to the observation-session metadata file.

    Written by `cmcp up` / `cmcp tmux` / `cmcp zellij` when a session
    is first created; read on every subsequent attach so version
    mismatches can be surfaced before the user ends up with a pane
    full of a now-stale agent or watch process.
    """
    return central_mcp_home() / "session-info.toml"
