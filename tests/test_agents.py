"""Consistency tests for `central_mcp.agents` — the single source of
truth for agent capabilities.

If a new agent is added to the registry but one of its declared
capabilities isn't actually implemented (adapter missing, quota module
missing, install function missing, etc.), these tests fail and point
at the drift. Keeps the registry honest.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from central_mcp import agents


class TestRegistryInternals:
    def test_registry_is_non_empty(self) -> None:
        assert agents.all_names(), "AGENTS dict should not be empty"

    def test_canonical_names_are_lowercase(self) -> None:
        for name in agents.AGENTS:
            assert name == name.lower(), f"{name!r} should be lowercase"

    def test_get_returns_none_for_unknown(self) -> None:
        assert agents.get("does-not-exist") is None

    def test_filter_by_returns_only_matches(self) -> None:
        orchestrators = agents.filter_by(can_orchestrate=True)
        assert all(a.can_orchestrate for a in orchestrators)
        assert len(orchestrators) < len(agents.AGENTS)      # some are dispatch-only

    def test_legacy_reexports_derive_from_registry(self) -> None:
        # VALID_AGENTS ↔ can_dispatch
        assert agents.VALID_AGENTS == frozenset(
            a.name for a in agents.AGENTS.values() if a.can_dispatch
        )
        # ORCHESTRATORS ↔ can_orchestrate (preserve original tuple shape)
        assert agents.ORCHESTRATORS == [
            (a.name, a.binary, a.label)
            for a in agents.AGENTS.values() if a.can_orchestrate
        ]
        # SUPPORTED_CLIENTS ↔ mcp_installable
        assert agents.SUPPORTED_CLIENTS == [
            a.name for a in agents.AGENTS.values() if a.mcp_installable
        ]


class TestCapabilityImplementationsMatchDeclarations:
    """Every True capability must have a real implementation wired up.
    These tests catch drift when someone flips a flag without adding
    the corresponding module / function / class."""

    def test_can_dispatch_agents_have_adapter(self) -> None:
        from central_mcp.adapters import get_adapter
        for a in agents.filter_by(can_dispatch=True):
            adapter = get_adapter(a.name)
            assert adapter.has_exec, (
                f"{a.name!r} declared can_dispatch=True but get_adapter "
                f"returns a fallback. Add a dispatch adapter in "
                f"src/central_mcp/adapters/base.py."
            )

    def test_has_quota_api_agents_have_module(self) -> None:
        for a in agents.filter_by(has_quota_api=True):
            try:
                mod = importlib.import_module(f"central_mcp.quota.{a.name}")
            except ImportError:
                raise AssertionError(
                    f"{a.name!r} declared has_quota_api=True but "
                    f"central_mcp.quota.{a.name} doesn't exist."
                )
            assert callable(getattr(mod, "fetch", None)), (
                f"{a.name!r}: quota module must expose a `fetch()` function."
            )

    def test_has_session_reader_agents_are_registered(self) -> None:
        from central_mcp import orch_session
        for a in agents.filter_by(has_session_reader=True):
            assert a.name in orch_session._READERS, (
                f"{a.name!r} declared has_session_reader=True but isn't "
                f"in `orch_session._READERS`."
            )

    def test_mcp_installable_agents_have_installer(self) -> None:
        from central_mcp import install
        for a in agents.filter_by(mcp_installable=True):
            fn = install._installer_for(a.name)
            assert callable(fn), (
                f"{a.name!r} declared mcp_installable=True but "
                f"install._installer_for returns None."
            )


class TestNoReverseDrift:
    """The registry should also cover every concrete implementation —
    no adapter / quota module / reader / installer should exist for an
    agent that isn't declared in AGENTS.
    """

    def test_every_adapter_class_has_registry_entry(self) -> None:
        # Adapters register themselves in the _ADAPTERS dict; their keys
        # must be a subset of AGENTS.
        from central_mcp.adapters.base import _ADAPTERS
        for name in _ADAPTERS:
            assert name in agents.AGENTS, (
                f"Adapter registered for {name!r} but not in agents.AGENTS. "
                f"Add a capability entry."
            )

    def test_every_quota_module_has_registry_entry(self) -> None:
        # A quota module can exist even when `has_quota_api=False` — e.g.
        # Gemini's module returns auth-type info only (for the monitor
        # status row), not real usage percentages. We only assert that
        # the agent is in AGENTS; the has_quota_api flag reflects
        # "usable for quota-based fallback decisions", which is stricter
        # than "module file exists".
        # `render` is a presentation-layer helper (HUD markdown), not an
        # agent quota fetcher — skip it.
        non_agent_modules = {"render"}
        quota_dir = Path(importlib.import_module("central_mcp.quota").__file__).parent
        for p in quota_dir.glob("*.py"):
            name = p.stem
            if name == "__init__" or name in non_agent_modules:
                continue
            assert name in agents.AGENTS, (
                f"Quota module {name!r} exists but agent isn't in AGENTS."
            )
