"""Coding-agent capability registry — the single source of truth for
what central-mcp knows about each supported CLI.

Every other module (cli pickers, dispatch adapter lookup, quota
fetcher selection, orchestrator-session reader routing, MCP install
target list) derives its view from the `AGENTS` table below. Adding a
new agent means one entry here plus whatever capability implementations
you declared — consistency tests in `tests/test_agents.py` fail if the
declarations drift from the real code.

Legacy re-exports (`ORCHESTRATORS`, `VALID_AGENTS`, `SUPPORTED_CLIENTS`)
are kept so pre-existing imports keep working; new callers should
prefer `filter_by(...)` / `installed(...)` for readability.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AgentCapabilities:
    """What central-mcp can and cannot do with a given coding-agent CLI."""

    # Identity
    name:   str     # canonical short name ("claude")
    binary: str     # PATH executable name ("claude")
    label:  str     # human-readable label ("Claude Code")

    # Boolean capabilities — each toggles a specific code path elsewhere.
    can_dispatch:       bool    # has a dispatch adapter (exec_argv / parse_output)
    can_orchestrate:    bool    # `central-mcp run` can launch this as the MCP client
    mcp_installable:    bool    # `central-mcp install` can register this client
    has_quota_api:      bool    # `central_mcp.quota.<name>` fetches real quota data
    has_session_reader: bool    # `orch_session` can backfill per-turn tokens


AGENTS: dict[str, AgentCapabilities] = {
    "claude": AgentCapabilities(
        name="claude", binary="claude", label="Claude Code",
        can_dispatch=True, can_orchestrate=True, mcp_installable=True,
        has_quota_api=True, has_session_reader=True,
    ),
    "codex": AgentCapabilities(
        name="codex", binary="codex", label="Codex CLI",
        can_dispatch=True, can_orchestrate=True, mcp_installable=True,
        has_quota_api=True, has_session_reader=True,
    ),
    "gemini": AgentCapabilities(
        name="gemini", binary="gemini", label="Gemini CLI",
        can_dispatch=True, can_orchestrate=True, mcp_installable=True,
        # `/stats model` is a local session counter, not a usable quota
        # API; Gemini CLI doesn't persist conversations to disk either.
        has_quota_api=False, has_session_reader=False,
    ),
    "opencode": AgentCapabilities(
        name="opencode", binary="opencode", label="opencode",
        can_dispatch=True,
        can_orchestrate=True,        # fix for historical drift in ORCHESTRATORS
        mcp_installable=True,
        has_quota_api=False,
        # Planned: opencode session reader via `opencode export` CLI.
        has_session_reader=False,
    ),
    "droid": AgentCapabilities(
        name="droid", binary="droid", label="Factory Droid",
        can_dispatch=True,
        # Policy: droid is a dispatch-target only, never an orchestrator.
        can_orchestrate=False,
        mcp_installable=False,
        has_quota_api=False, has_session_reader=False,
    ),
}


# ── query helpers ───────────────────────────────────────────────────────────

def get(name: str) -> AgentCapabilities | None:
    """Return the capabilities for `name`, or None if unknown."""
    return AGENTS.get(name)


def all_names() -> list[str]:
    return list(AGENTS.keys())


def filter_by(**caps: bool) -> list[AgentCapabilities]:
    """Return agents matching every listed capability flag.

    Example: `filter_by(can_orchestrate=True, has_quota_api=True)`.
    """
    return [
        a for a in AGENTS.values()
        if all(getattr(a, k, None) == v for k, v in caps.items())
    ]


def installed(filter_fn: Callable[[AgentCapabilities], bool] | None = None
              ) -> list[AgentCapabilities]:
    """Return agents whose `binary` is on PATH now. Optional filter_fn
    (lambda over `AgentCapabilities`) narrows the candidate set before
    the PATH check.
    """
    candidates = (
        AGENTS.values() if filter_fn is None
        else [a for a in AGENTS.values() if filter_fn(a)]
    )
    return [a for a in candidates if shutil.which(a.binary)]


def is_installed(name: str) -> bool:
    cap = AGENTS.get(name)
    return bool(cap and shutil.which(cap.binary))


# ── legacy re-exports (back-compat) ─────────────────────────────────────────

# Keep the exact shapes other modules used to declare directly. New
# callers should use filter_by / installed instead — richer and read
# from the same source of truth.

#: dispatch-capable agent names (for adapters / server validation)
VALID_AGENTS: frozenset[str] = frozenset(
    a.name for a in AGENTS.values() if a.can_dispatch
)

#: (name, binary, label) triples for the `central-mcp run` picker
ORCHESTRATORS: list[tuple[str, str, str]] = [
    (a.name, a.binary, a.label)
    for a in AGENTS.values() if a.can_orchestrate
]

#: MCP-installable clients (targets of `central-mcp install`)
SUPPORTED_CLIENTS: list[str] = [
    a.name for a in AGENTS.values() if a.mcp_installable
]
