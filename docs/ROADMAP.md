---
description: Forward-looking plan for central-mcp — visibility, routing, upstream agents, workspaces, ecosystem alignment, distribution, and architecture tracks. Suggestions welcome via GitHub issues.
---

# Roadmap

What's planned for central-mcp. This page is **forward-looking only** — for what's already shipped, see the [Changelog](changelog.md).

> **Have a suggestion?** Open an issue at [github.com/andy5090/central-mcp/issues](https://github.com/andy5090/central-mcp/issues). We read every one.

Status legend: 📋 planned · 💭 idea · 🚧 in progress

## Where central-mcp sits in the 2026 stack

The coding-agent ecosystem has settled into a three-layer shape: **IDE agents** for real-time collaboration, **local CLI agents** for terminal execution, and **cloud agents** for asynchronous delegation. Orchestration is also standardizing — Claude Code ships native agent teams for in-repo parallelism, and cross-vendor protocols (MCP's Tasks extension, A2A 1.0) now cover long-running delegated work.

central-mcp's lane is the one none of those cover: **cross-project, cross-vendor dispatch from one terminal-native hub.** Agent teams parallelize one repo under one vendor; central-mcp routes work across your whole portfolio to whichever agent CLI each project uses. That positioning drives the priorities below — protocol alignment where standards emerged (Tasks, A2A), and doubling down on the visibility/routing layer no single-vendor tool provides.

---

## Visibility

Make the project-portfolio view consistent across every surface, and close the gap between "dispatch is running" and "I can see what it's doing."

### Result retrieval

📋 **`tail_dispatch(dispatch_id, since_ts=null)` MCP tool.** Returns recent output chunks since a timestamp without waiting for completion. Today `check_dispatch` only fills `output` once the subprocess exits — orchestrators (and the TUI sidebar) can't show progress text mid-run without parsing `dispatch.jsonl` themselves. This tool encapsulates that.

📋 **`dispatches` table progress columns.** Add `last_output_ts`, `output_bytes`, `attempt_count` to the existing schema. Cheap update on every output chunk; reads power "is this dispatch still alive vs. wedged?" indicators in every observation surface.

💭 **`wait_for_dispatch(dispatch_id, timeout_sec=300)` MCP tool.** Server-side polling that blocks until the dispatch terminates, then returns the row. Closes the "codex / gemini are bad at sustained polling" gap — the LLM makes one tool call instead of running a polling loop. claude already polls fine; this is for the others. If the [MCP Tasks alignment](#ecosystem-alignment) lands first, clients that speak the Tasks extension get this behavior natively and the tool shrinks to a compatibility shim.

### Visualization

📋 **TUI sidebar expanded row.** Selected dispatch row expands to show: live tail of last N output lines, elapsed, token delta, "last output Xs ago" health hint. Other rows stay collapsed. Builds directly on `tail_dispatch` + the new schema columns.

📋 **Reuse `token_usage.summary_markdown` in `cmcp monitor` and `cmcp watch`.** The pre-rendered HUD shipped in 0.10.18 is currently only seen by orchestrators. Wiring it into the curses monitor and the watch-pane sticky header eliminates rendering drift across surfaces.

📋 **Token budgets + alerts.** Per-project / per-workspace token caps in `config.toml`; threshold breaches trigger a yellow banner at dispatch start, and the existing quota-aware fallback chain extends to budget-aware fallback at 90%.

💭 **Heuristic progress markers.** Parse output streams for meaningful events — file reads / writes, tool calls, test runs, build steps — and surface them as a per-dispatch badge stripe ("I/O: 2 reads · Tools: 5 · Tests: 3✓"). Patterns are agent-specific, so they live on `agents.AGENTS` adapter records as `progress_markers: list[regex]`.

💭 **Dispatch detail screen.** TUI keybinding (Enter) drills a row into a full-screen view: prompt / output / chain / tokens / duration / progress-marker timeline. Markdown rendering when output is markdown; raw text otherwise.

💭 **Watch mode: cumulative consumption next to elapsed time.** Show `+ 42s · 8.97M tokens` rather than `+ 42s` alone, so long-running dispatches make their cost visible.

---

## TUI · 1.0 milestone

A self-contained terminal app that hosts the orchestrator agent inside a managed PTY, surrounds it with our own chrome (token HUD, active dispatches, notifications), and reacts to dispatch completion *immediately* — no longer dependent on the MCP client forwarding `notifications/resources/updated`. The track that **defines 1.0**: when this lands stable across all four orchestrators, central-mcp graduates from 0.x to 1.0.0 and starts honoring SemVer guarantees.

✅ **Phase 0 (0.12.0) — `cmcp tui --experimental`, claude only.** Shipped 2026-05-03. `textual` for outer chrome (header / sidebar / footer / notifications), `pyte` for PTY emulation. Inside the main pane: claude REPL pass-through. Sidebar: `token_usage.summary_markdown` + active dispatches + recent completions. Daemon-style watcher on `dispatches.db` raises notifications inline. `--experimental` flag is required (no flag → actionable error). Optional install via `pip install 'central-mcp[tui]'`.

✅ **Phase B (0.12.2) — codex.** Shipped 2026-05-10. Same chrome, second agent on the allowlist; `--agent claude|codex` now a constrained choice and the CSI / whitespace-emphasis fixes from Phase 0 cover both.

📋 **Phase C (0.13.0) — opencode + gemini.** Round out the four orchestrators central-mcp already knows. opencode goes first — its adoption curve (147k GitHub stars, ~6.5M monthly developers by spring 2026) makes it the most-requested gap, and its provider-agnostic design exercises the PTY chrome differently than the vendor CLIs do.

📋 **Phase D (0.14.0–0.x) — stabilization.** Self-rendered scrollback / search / copy. Korean IME and double-width corner cases. Notification policy fine-tuning (`config.toml [tui].auto_inject = passive | hint | prompt`).

🎉 **1.0.0 — TUI production-ready.** `--experimental` flag becomes a no-op (kept for backwards compatibility), API surface is locked, version-pinning windows close, breaking changes require a 2.0.

💭 **Open questions**
- Multi-pane layout — does the TUI host more than one watch pane internally, or does it stay single-pane and let users compose with their existing multiplexer (cmux / tmux / zellij) on top?
- How transparent should prompt-injection be? `hint` mode shows a sidebar message and stops; `prompt` mode types the literal hint into the agent's stdin. The line between "helpful" and "intrusive" is blurry.

---

## Live agent panes

A second execution mode — opt-in, session-scoped, complementary to the default non-interactive dispatch path.

Today every dispatch is a fresh subprocess with `stdin=DEVNULL`, which forces `--dangerously-skip-permissions` (bypass mode) on every agent so prompts that pause for confirmation don't hang the dispatch forever. PTY mode runs the agent inside a real TTY pair, so permission prompts surface in a live pane the user can answer in real time, conversation context can persist across turns, and prompt-cache stays warm. The trade-off is one resident agent process per active project, so this is for the 2–3 projects you're actively supervising — not the whole portfolio.

The two modes share the same data model (`dispatches.db` + `dispatch.jsonl` with `mode="pty"` marker), so `cmcp watch`, the TUI sidebar, and `orchestration_history` all surface both kinds without modification.

✅ **Building blocks (0.12.2).** `PtyTerminal(project=, agent=, cwd=)` doubles as a dispatch event writer: `submit_prompt(text)` records `start` / `complete` rows in `dispatches.db` and matching events in `dispatch.jsonl`. A screen-stability watcher (cursor + bottom 6 rows hash-match for 1.5s) flips status to `complete`. PTY-mode dispatches are indistinguishable from MCP-mode dispatches to readers — only the `mode="pty"` marker differs.

📋 **`pty_sessions/<project>.json` lifecycle + dispatch guard.** PTY widget registers `{pid, agent, started_at}` on spawn, removes on unmount; stale-PID cleanup on read. `dispatch()` consults the registry and rejects calls into projects with an active PTY (`{ok: false, error: "...", mode: "pty"}`) so background fan-out can't inject prompts mid-conversation while a human is driving the pane.

📋 **Output capture for PTY mode.** `pyte.HistoryScreen` (10000-row scrollback) feeds a `_capture_text()` helper that snapshots the full session into `dispatches.output` on `_mark_complete`. Closes the documented gap from 0.12.2 where PTY-mode dispatches left `output` empty. `check_dispatch(did)` then returns the same shape regardless of execution mode.

📋 **`pty_inbox` queue + `pty_submit(project, prompt)` MCP tool.** Cross-process prompt routing: orchestrator calls `pty_submit` from any process, which inserts a row into a small SQLite inbox table. The TUI's PtyTerminal polls every 250ms (its own project only) and routes pulled rows through `submit_prompt()`. SQLite is the transport because the same pattern already works for `dispatches.db`; MCP stays at the API surface only.

📋 **`list_projects` exposes mode.** Each row carries `mode: "pty" | "mcp"` derived from the `pty_sessions/` registry, so orchestrators see at a glance which projects are PTY-bound and pick `pty_submit` vs `dispatch` accordingly. Plus a one-line policy in `data/CLAUDE.md` so the LLM-side guidance matches the registry-side enforcement.

💭 **Optional PTY panes in tmux / zellij / cmux layouts.** Today `cmcp tmux` / `cmcp zellij` populates project panes with `central-mcp watch <p>` (passive jsonl tail). A flag like `--mode=pty` or per-project override could populate a pane with the project's agent CLI directly — the user gets a live, interactive supervision pane instead of a passive log tail. The watch path stays available for projects you don't want to keep an agent resident for.

💭 **Persistent REPL conversation context.** Long-lived agent REPL means a follow-up dispatch doesn't lose what the previous one established — caching is automatic, no `--resume` plumbing needed. Trade-off: state drift / context bloat. Need a "/clear" hook or session-rotation policy. Probably opt-in.

💭 **Permission prompt visibility.** With PTY mode, agents can run **without** `--dangerously-skip-permissions` because the prompt surfaces in a pane the user can answer. A future `[live].permissions = ask | bypass` config keys the per-project default, with `ask` being the genuinely safer (and previously impossible) choice.

---

## Routing

Move from "user picks the agent for every dispatch" to "central-mcp suggests."

The case for this track has strengthened: frontier CLIs have converged on raw capability (Terminal-Bench 2.1 puts Codex CLI and Claude Code within half a point of each other), so the interesting routing signals are no longer "which agent is smarter" but **cost, quota headroom, task shape, and project fit** — exactly the state central-mcp already tracks per agent.

📋 **`suggest_dispatch(project, prompt)` MCP tool.** Returns `{agent, model, reasoning, fallback}` without dispatching — orchestrators show the suggestion, the user accepts or overrides. Heuristics first (prompt length, keywords like "refactor" / "research" / "review", current quota state); LLM-assisted classifier later if it earns its keep.

📋 **Budget-aware fallback chain.** The existing quota-aware chain (saved preference → fallback → remaining installed) extends to also skip agents over their configured token budget. Ties Visibility's budget work into Routing.

💭 **`auto_dispatch` opt-in.** Combined classify + dispatch, gated behind `config.toml [routing].auto = true`. Only after `suggest_dispatch` data shows users accept recommendations >70% of the time.

💭 **Per-workspace routing overrides.** Different favored agents per workspace (e.g. workspace `client-a` defaults to claude, `client-b` to codex).

---

## Upstream agents

Open the orchestrator to programmatic callers — personal autonomous agents (scheduled daemons, persistent self-referential loops, chat / browser bridges) that want to delegate work to central-mcp without a human in the REPL.

Today the orchestrator only exists as the interactive REPL launched by `cmcp run`. Upstream MCP clients can call `dispatch` directly, but doing so skips the orchestrator's routing / fallback / localization / conflict-detection layer — losing the value central-mcp adds. Closing that gap means giving the orchestrator a non-interactive entry channel.

✅ **Hermes Agent (Nous Research) integration (0.12.2).** Hermes is the OpenClaw successor — a self-improving agentOS with multi-platform delivery (Telegram / Discord / Slack), built-in cron, skill curation, and bidirectional MCP. The new `_Hermes` adapter wraps `hermes -z PROMPT` for dispatch (`--continue` / `--resume <id>` / `--yolo --accept-hooks` for bypass) and `cmcp install hermes` writes central-mcp into `~/.hermes/config.yaml` so Hermes's LLM sees `dispatch` / `list_projects` / `check_dispatch` as native tools. With `cmcp run --agent hermes` Hermes becomes the orchestrator; with `add_project --agent hermes` it becomes a dispatch target — chosen per project. Hermes's gateway layer is a natural place to surface dispatch completions to non-CLI surfaces (Telegram alert when a long dispatch finishes), and its cron lets daily / weekly central-mcp summaries land on chat platforms without us building a bot.

📋 **`dispatch_orchestrator(prompt, agent=None, workspace=None)` MCP tool.** Spawns a fresh non-interactive orchestrator subprocess (claude `-p`, codex `exec`, gemini `-p`, opencode equivalent), loads central-mcp's MCP tools, hands it the prompt, and returns a `dispatch_id` mirroring `dispatch` semantics — caller polls `check_dispatch` for the final stdout. Reuses `_launch_dispatch` plumbing.

📋 **`cmcp ask "<prompt>"` CLI.** Synchronous shell wrapper over `dispatch_orchestrator` for upstream agents that don't speak MCP. Same agent resolution as `cmcp run`.

💭 **Per-agent non-interactive MCP-loading verification.** claude `-p` and codex `exec` are confirmed paths; gemini `-p` and opencode need a small spike. Phasing mirrors the TUI track — claude first, others follow.

💭 **Persistent orchestrator session.** Reuse one long-lived orchestrator across many upstream calls instead of spawning per ask. Only justified once usage data shows spawn cost is non-negligible relative to LLM latency.

💭 **A2A endpoint for the orchestrator.** A2A hit 1.0 under the Linux Foundation with 150+ backing organizations — it's becoming the lingua franca for agent-to-agent delegation, complementary to MCP (A2A between agents, MCP between an agent and its tools). Exposing `dispatch_orchestrator` behind a thin A2A server would let any A2A-speaking agent (enterprise frameworks, cloud agents, other people's daemons) delegate portfolio work to central-mcp without knowing MCP or our CLI. Gated on `dispatch_orchestrator` landing first and on a concrete upstream consumer showing up — we won't build the endpoint before the caller exists.

💭 **Cloud agents as dispatch targets.** The 2026 stack splits work across local CLIs and asynchronous cloud agents (Codex cloud tasks, Claude Code cloud sessions). Dispatch today always means "local subprocess in the project's cwd"; a `target: cloud` variant would hand the prompt to the agent's cloud backend and poll its API for completion instead of a PID. Same `dispatch_id` / `check_dispatch` contract, different executor. Needs per-vendor API stability first — the surfaces are still churning.

---

## Workspaces

Per-process workspace scoping (`CMCP_WORKSPACE`) is shipped. Next steps are about session-level visibility and shared context.

📋 **Persistent session IDs.** New `sessions` table tracking each `cmcp run` instance — `id`, `workspace`, `started_at`, `last_seen_at`, `pid`, `terminal_kind`. Backs a new `cmcp sessions ls` command and links each `dispatch_id` to the session that initiated it. Useful when running 3+ concurrent workspaces and wanting to see which terminal owns which dispatch.

📋 **Per-session history view.** `orchestration_history(session=<id>)` returns only the dispatches initiated by that session. Optional, off by default — most users only need workspace-level isolation.

💭 **Per-workspace `CLAUDE.md` / `AGENTS.md` overlays.** `~/.central-mcp/workspaces/<name>/AGENTS.md` augments the base orchestrator instructions when launching that workspace. Useful for client engagements with distinct working agreements.

💭 **Shared context: per-workspace user prompts.** A workspace-specific `user.md` overlay applied to every dispatch inside that workspace.

---

## Ecosystem alignment

The MCP spec is going through its largest revision since launch — the **2026-07-28 release** makes the protocol core stateless (no `initialize` handshake, no session header, capabilities in `_meta` per request) and promotes long-running work to an official **Tasks extension**: a server answers `tools/call` with a task handle, and the client drives it with `tasks/get` / `tasks/update` / `tasks/cancel`.

That lifecycle is *exactly* the `dispatch` → `check_dispatch` → `cancel_dispatch` pattern central-mcp has shipped since day one — we independently converged on the design the protocol just standardized. Aligning with it costs little and buys native client support.

It turned out we didn't even need the v2 beta to start: the installed stack (fastmcp 3.x on mcp 1.x) already carries the experimental Tasks protocol types from the 2025-11-25 spec, so Phases 1–2 shipped on it directly. Phasing:

✅ **Phase 1 — task-model groundwork, no SDK dependency.** Shipped: `tasks_adapter` module translating the dispatch status vocabulary onto the Tasks lifecycle (`working` / `input_required` / `completed` / `failed` / `cancelled`) and rendering dispatch entries as spec-shaped task objects. Audit of the deprecating trio (Roots / Sampling / Logging — 12-month window) came back clean. Notes in `docs/architecture/mcp-2026-spec-prep.md`.

✅ **Phase 2 — Tasks wire, behind a flag.** Shipped: with `CENTRAL_MCP_TASKS=1`, the server registers `tasks/get` / `tasks/cancel` / `tasks/result` handlers backed by the same `dispatches.db` state — taskId is the dispatch_id. `check_dispatch` / `cancel_dispatch` stay as-is indefinitely; the extension is an additional wire shape over the same state, not a replacement. `tasks/list` is deliberately not served (the 2026-07-28 release removes it). Flag-off default is byte-identical to before.

📋 **Phase 3 (on stable v2) — migrate shape + flip the default.** When fastmcp / the official SDK ship the final extension model, migrate the Phase-2 handlers from the experimental core-protocol shape to the official Tasks extension (capability advertisement, `tools/call` returning task handles), drop the flag, and do the mechanical stateless-core conformance sweep. central-mcp is already stateless between requests by design (a load-bearing invariant), so no architectural work is expected here.

💭 **Agent-teams complement note.** Claude Code's native agent teams (experimental) parallelize teammates *within one repo and one vendor*. The two compose rather than compete: a team lead session can carry central-mcp's MCP tools and dispatch cross-project work mid-team-session. Worth a short recipe in `data/CLAUDE.md` once agent teams exit experimental — same pattern as the cmux recipe, documentation not code.

---

## Distribution

📋 **Auto-generate CLI + MCP-tool reference pages.** Today the [CLI](cli.md) and [MCP tools](mcp-tools.md) pages are hand-curated. A small `scripts/gen_docs.py` walks `argparse._SubParsersAction` and `inspect.signature` over `server.py`, regenerates these pages, and a CI guard fails the build if they drift from source.

💭 **Windows installer (PowerShell).** macOS + Linux work via `install.sh`. A PowerShell parallel would unblock Windows users; pure-Python core already runs there, the friction is install + alias setup.

---

## Architecture

The slow-burn changes — only land when usage data justifies the complexity.

💭 **Push notifications via MCP.** Server-initiated `notifications/resources/updated` for dispatch completion. The 2026-07-28 spec direction argues *against* this ever landing: the protocol core went stateless and poll-first (the Tasks extension deliberately replaced push-style results with `tasks/get` polling), so server-initiated notification support in clients is more likely to shrink than grow. `cmcp tui` (direct db polling) stays the recommended completion-alert path, and the [Tasks mapping](#ecosystem-alignment) is the standards-track answer for MCP callers. Kept as an idea only in case a client ships first-class notification surfacing anyway.

💭 **Agent capability registry overrides.** Today's `agents.AGENTS` is the single source of truth. A `[agents.<name>]` block in `config.toml` would let users override capabilities per-host (e.g. mark codex `has_quota_api = false` in environments where the OAuth flow is broken).

---

## Non-goals

These are deliberate "we won't do this" — saving everyone time:

- **Browser UI.** central-mcp is terminal-native. Observation lives in tmux/zellij panes or by tailing logs.
- **Agent-state syncing.** Each agent CLI manages its own conversation state. central-mcp orchestrates dispatches, observes their lifecycle, and aggregates token use — it doesn't replicate session history.
- **Interactive approval baked into `dispatch()`.** Default dispatch stays non-interactive — `stdin=DEVNULL`, bypass mode, no human in the loop. Mid-run approval lives on the [Live agent panes](#live-agent-panes) track instead, opt-in per session via PTY panes. The two paths share data and registry; the policy choice is per-project, not global.
- **In-repo agent teams / swarms.** Parallelizing multiple agents inside one repository is the vendors' home turf (Claude Code agent teams, Codex multi-agent, and a crowded field of community orchestrators). central-mcp stays one level up: one dispatch per project, across projects and vendors. If you need five agents on one repo, run your vendor's team feature inside a project central-mcp dispatched to.
- **Separate daemon process.** `cmcp tui` is the long-running watcher — its asyncio task tails `dispatches.db` independently of any LLM turn and surfaces completions directly. No second process to install, manage, or debug.

---

## Suggesting changes

Have a use case that doesn't fit anywhere above? An idea for a new MCP tool? A "this is slowing me down every day" complaint?

→ **[Open a GitHub issue](https://github.com/andy5090/central-mcp/issues/new)** with a short description and your context (which orchestrator, which workspace, what you tried). Real usage signals shape the roadmap more than abstract phasing — one good issue often promotes a 💭 to 📋.
