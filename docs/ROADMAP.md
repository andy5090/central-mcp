---
description: Forward-looking plan for central-mcp — visibility, routing, workspaces, distribution, and architecture tracks. Suggestions welcome via GitHub issues.
---

# Roadmap

What's planned for central-mcp. This page is **forward-looking only** — for what's already shipped, see the [Changelog](changelog.md).

> **Have a suggestion?** Open an issue at [github.com/andy5090/central-mcp/issues](https://github.com/andy5090/central-mcp/issues). We read every one.

Status legend: 📋 planned · 💭 idea · 🚧 in progress

---

## Visibility

Make the project-portfolio view consistent across every surface.

📋 **Reuse `token_usage.summary_markdown` in `cmcp monitor` and `cmcp watch`.** The pre-rendered HUD shipped in 0.10.18 is currently only seen by orchestrators. Wiring it into the curses monitor and the watch-pane sticky header eliminates rendering drift across surfaces.

📋 **Token budgets + alerts.** Per-project / per-workspace token caps in `config.toml`; threshold breaches trigger a yellow banner at dispatch start, and the existing quota-aware fallback chain extends to budget-aware fallback at 90%.

💭 **Watch mode: cumulative consumption next to elapsed time.** Show `+ 42s · 8.97M tokens` rather than `+ 42s` alone, so long-running dispatches make their cost visible.

---

## Routing

Move from "user picks the agent for every dispatch" to "central-mcp suggests."

📋 **`suggest_dispatch(project, prompt)` MCP tool.** Returns `{agent, model, reasoning, fallback}` without dispatching — orchestrators show the suggestion, the user accepts or overrides. Heuristics first (prompt length, keywords like "refactor" / "research" / "review", current quota state); LLM-assisted classifier later if it earns its keep.

📋 **Budget-aware fallback chain.** The existing quota-aware chain (saved preference → fallback → remaining installed) extends to also skip agents over their configured token budget. Ties Visibility's budget work into Routing.

💭 **`auto_dispatch` opt-in.** Combined classify + dispatch, gated behind `config.toml [routing].auto = true`. Only after `suggest_dispatch` data shows users accept recommendations >70% of the time.

💭 **Per-workspace routing overrides.** Different favored agents per workspace (e.g. workspace `client-a` defaults to claude, `client-b` to codex).

---

## Workspaces

Per-process workspace scoping (`CMCP_WORKSPACE`) is shipped. Next steps are about session-level visibility and shared context.

📋 **Persistent session IDs.** New `sessions` table tracking each `cmcp run` instance — `id`, `workspace`, `started_at`, `last_seen_at`, `pid`, `terminal_kind`. Backs a new `cmcp sessions ls` command and links each `dispatch_id` to the session that initiated it. Useful when running 3+ concurrent workspaces and wanting to see which terminal owns which dispatch.

📋 **Per-session history view.** `orchestration_history(session=<id>)` returns only the dispatches initiated by that session. Optional, off by default — most users only need workspace-level isolation.

💭 **Per-workspace `CLAUDE.md` / `AGENTS.md` overlays.** `~/.central-mcp/workspaces/<name>/AGENTS.md` augments the base orchestrator instructions when launching that workspace. Useful for client engagements with distinct working agreements.

💭 **Shared context: per-workspace user prompts.** A workspace-specific `user.md` overlay applied to every dispatch inside that workspace.

---

## Distribution

📋 **Auto-generate CLI + MCP-tool reference pages.** Today the [CLI](cli.md) and [MCP tools](mcp-tools.md) pages are hand-curated. A small `scripts/gen_docs.py` walks `argparse._SubParsersAction` and `inspect.signature` over `server.py`, regenerates these pages, and a CI guard fails the build if they drift from source.

💭 **Windows installer (PowerShell).** macOS + Linux work via `install.sh`. A PowerShell parallel would unblock Windows users; pure-Python core already runs there, the friction is install + alias setup.

---

## Architecture

The slow-burn changes — only land when usage data justifies the complexity.

💭 **Lazy daemon.** First MCP connection spawns a background daemon, holds a PID lock, exposes a Unix socket; stdio `central-mcp serve` auto-detects and proxies. Wins: ~150ms cold-start saved per MCP client, centralized session scanners, single place for pre-work. Cross-process state already solved by `dispatches.db` in 0.10.9, so the urgency is low.

💭 **Push notifications when MCP clients forward them.** Server-initiated `notifications/resources/updated` events for completed dispatches. Currently blocked: no MCP client surfaces these to the LLM turn yet. Tracking upstream; will land when at least one client commits to forwarding.

💭 **Agent capability registry overrides.** Today's `agents.AGENTS` is the single source of truth. A `[agents.<name>]` block in `config.toml` would let users override capabilities per-host (e.g. mark codex `has_quota_api = false` in environments where the OAuth flow is broken).

---

## Non-goals

These are deliberate "we won't do this" — saving everyone time:

- **Browser UI.** central-mcp is terminal-native. Observation lives in tmux/zellij panes or by tailing logs.
- **Agent-state syncing.** Each agent CLI manages its own conversation state. central-mcp orchestrates dispatches, observes their lifecycle, and aggregates token use — it doesn't replicate session history.
- **Interactive approval / worker mode.** Dispatch is non-interactive by design. If a user needs to approve actions mid-run, they should run the agent directly in a terminal.
- **`central-mcp install <client>` replacement of stdio.** Even after daemon mode lands, stdio stays the default transport. Daemon proxies behind it, transparent to clients.

---

## Suggesting changes

Have a use case that doesn't fit anywhere above? An idea for a new MCP tool? A "this is slowing me down every day" complaint?

→ **[Open a GitHub issue](https://github.com/andy5090/central-mcp/issues/new)** with a short description and your context (which orchestrator, which workspace, what you tried). Real usage signals shape the roadmap more than abstract phasing — one good issue often promotes a 💭 to 📋.
