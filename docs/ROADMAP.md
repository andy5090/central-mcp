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

## TUI · 1.0 milestone

A self-contained terminal app that hosts the orchestrator agent inside a managed PTY, surrounds it with our own chrome (token HUD, active dispatches, notifications), and reacts to dispatch completion *immediately* — no longer dependent on the MCP client forwarding `notifications/resources/updated`. The track that **defines 1.0**: when this lands stable across all four orchestrators, central-mcp graduates from 0.x to 1.0.0 and starts honoring SemVer guarantees.

🚧 **Phase 0 (0.12.0) — `cmcp tui --experimental`, claude only.** New experimental subcommand. `textual` for outer chrome (header / sidebar / footer / notifications), `pyte` for PTY emulation. Inside the main pane: claude REPL pass-through. Sidebar: `token_usage.summary_markdown` + active dispatches + recent completions. Daemon-style watcher on `dispatches.db` raises notifications inline. `--experimental` flag is required (no flag → actionable error). Optional install via `pip install central-mcp[tui]`.

📋 **Phase B (0.13.0) — codex.** Same shell, second agent adapter. Adapter pattern lives in `adapters/base.py` already, extension is mechanical.

📋 **Phase C (0.14.0) — gemini + opencode.** Round out the four orchestrators central-mcp already knows.

📋 **Phase D (0.15.0–0.x) — stabilization.** Self-rendered scrollback / search / copy. Korean IME and double-width corner cases. Notification policy fine-tuning (`config.toml [tui].auto_inject = passive | hint | prompt`).

🎉 **1.0.0 — TUI production-ready.** `--experimental` flag becomes a no-op (kept for backwards compatibility), API surface is locked, version-pinning windows close, breaking changes require a 2.0.

💭 **Open questions**
- Multi-pane layout — does the TUI host more than one watch pane internally, or does it stay single-pane and let users compose with their existing multiplexer (cmux / tmux / zellij) on top?
- How transparent should prompt-injection be? `hint` mode shows a sidebar message and stops; `prompt` mode types the literal hint into the agent's stdin. The line between "helpful" and "intrusive" is blurry.

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

💭 **Push notifications via MCP.** Server-initiated `notifications/resources/updated` for dispatch completion. Lands when at least one MCP client commits to surfacing them to the LLM turn — until then, `cmcp tui` is the recommended completion-alert path.

💭 **Agent capability registry overrides.** Today's `agents.AGENTS` is the single source of truth. A `[agents.<name>]` block in `config.toml` would let users override capabilities per-host (e.g. mark codex `has_quota_api = false` in environments where the OAuth flow is broken).

---

## Non-goals

These are deliberate "we won't do this" — saving everyone time:

- **Browser UI.** central-mcp is terminal-native. Observation lives in tmux/zellij panes or by tailing logs.
- **Agent-state syncing.** Each agent CLI manages its own conversation state. central-mcp orchestrates dispatches, observes their lifecycle, and aggregates token use — it doesn't replicate session history.
- **Interactive approval / worker mode.** Dispatch is non-interactive by design. If a user needs to approve actions mid-run, they should run the agent directly in a terminal.
- **Separate daemon process.** `cmcp tui` is the long-running watcher — its asyncio task tails `dispatches.db` independently of any LLM turn and surfaces completions directly. No second process to install, manage, or debug.

---

## Suggesting changes

Have a use case that doesn't fit anywhere above? An idea for a new MCP tool? A "this is slowing me down every day" complaint?

→ **[Open a GitHub issue](https://github.com/andy5090/central-mcp/issues/new)** with a short description and your context (which orchestrator, which workspace, what you tried). Real usage signals shape the roadmap more than abstract phasing — one good issue often promotes a 💭 to 📋.
