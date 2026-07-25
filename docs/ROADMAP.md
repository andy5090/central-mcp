---
description: Forward-looking plan for central-mcp — reframed around its essence as a portfolio PM. Pulse briefings, status ledger, multi-agent collaboration, reporting surfaces, dispatch core, and ecosystem alignment. Suggestions welcome via GitHub issues.
---

# Roadmap

What's planned for central-mcp. This page is **forward-looking only** — for what's already shipped, see the [Changelog](changelog.md).

> **Have a suggestion?** Open an issue at [github.com/andy5090/central-mcp/issues](https://github.com/andy5090/central-mcp/issues). We read every one.

Status legend: 📋 planned · 💭 idea · 🚧 in progress

## The essence — a portfolio PM, not just a dispatch hub

*Reframed 2026-07. The previous positioning — "cross-project, cross-vendor dispatch from one terminal-native hub" — described the mechanism. This describes the job.*

central-mcp exists for one human problem: **a person running four or more agent-driven projects at once inevitably loses the thread.** Not because agents are slow — they've never been faster — but because nobody is playing PM. Every context switch charges a re-orientation tax: *what happened here while I was away? What state is it in? What was I about to do next?*

central-mcp's job is to be that PM. For every registered project it should always be able to tell you **what happened, where things stand, and what's next** — and tell you at the moments that matter: when you return to a project, when something finishes or fails, and on a regular digest cadence. The success metrics are simple: time-to-reorient on returning to a project approaches zero, and nothing falls through the cracks.

Everything else on this page serves that job:

- **Dispatch** (cross-project, cross-vendor) is the PM's *hands* — how delegated work gets done.
- **Surfaces** (TUI control tower, watch panes, live PTY panes) are the PM's *reporting channels*.
- **Multi-agent collaboration** is the PM running a *team* on one project instead of a single contractor.
- **Ecosystem endpoints** (MCP Tasks, A2A) let other agents consult the PM, not just humans.

The honest gap this rethink confronts: today the hub only knows about work that flows *through* it — `orchestration_history` reads dispatch events, so direct commits, interactive agent sessions, and manual edits are invisible. A real PM doesn't wait for status reports; it reads the repo. Closing that gap is the first item of the [Portfolio PM](#portfolio-pm) track.

Where this sits in the 2026 stack, condensed: vendors' agent teams parallelize *one repo under one vendor*; cloud agents absorb asynchronous single tasks; IDE agents pair in real time. central-mcp keeps the layer none of them occupy — the whole portfolio, across vendors — and now also reaches one level deeper: **cross-vendor collaboration inside a single project**, the combination no single-vendor team feature can offer.

---

## The 1.0 milestone — the PM works

1.0 was previously defined by TUI stability alone. Redefined: **1.0 ships when the PM loop demonstrably works across all four orchestrators.**

1. **Return briefing** — `project_pulse` plus the briefing recipe produce a trustworthy "what happened / where it stands / what's next" for any project, including work done outside central-mcp.
2. **Control tower** — the TUI hosts all four orchestrators stably (Phase D complete) with a portfolio-aware sidebar.
3. **Digest** — a scheduled portfolio digest lands somewhere you actually look (terminal, or chat via the Hermes bridge).

At 1.0 the TUI's `--experimental` flag becomes a no-op (kept for backwards compatibility), the API surface locks, and breaking changes require a 2.0.

---

## Portfolio PM

The new center-of-gravity track. Architecture is deliberately two-phase — **pulse first (stateless), ledger second (durable)** — so the PM's ground truth is always recomputed from the repo, and stored state is additive rather than load-bearing.

📋 **`project_pulse(project)` MCP tool + `cmcp pulse [project]`.** Stateless, on-demand aggregation of everything knowable about a project *right now*: git (current branch, recent commits, dirty files, ahead/behind upstream), dispatch history (recent outcomes, tokens), agent-session activity via the existing per-agent session readers, and open-PR state when `gh` is available. No new storage — the pulse is computed fresh on every call, so work done entirely outside central-mcp (direct commits, interactive sessions) shows up because git is the source of truth. This is the data spine every other PM feature stands on.

📋 **Return briefing.** The flagship PM moment: come back to a project after days away and get "what happened / where it stands / what's next" in one shot. `cmcp brief` upgrades from a registry listing to a pulse-powered portfolio digest, and a recipe in `data/{CLAUDE,AGENTS}.md` teaches orchestrators to synthesize a narrative briefing from `project_pulse` whenever the user switches context to a project.

📋 **Status ledger (phase 2).** `~/.central-mcp/projects/<name>/STATUS.md` — durable per-project memory: a structured delta appended when a dispatch completes (what was done, what was left), open questions, and a "next steps" list that survives across sessions and orchestrators. `cmcp note <project> "…"` adds manual entries. Briefings then combine ledger (intent, next steps) with pulse (ground truth) and flag drift between the two. Plain files, same as the registry — the stateless-between-requests invariant holds.

📋 **Push reporting.** Daily/weekly digests and event alerts (dispatch failed, long-running dispatch finished) delivered without a new daemon: the TUI watcher surfaces them locally, and the Hermes bridge (cron + Telegram/Discord gateway, shipped 0.12.2–0.14.0) carries them off-terminal. Promote the sketch in the Hermes skill to a first-class recipe with a pulse-powered digest format.

💭 **Ask-anything upgrade.** `orchestration_history` gains git-awareness — portfolio answers no longer limited to dispatch-driven events. Likely an `include_pulse` flag fanning out cheap per-project pulse reads.

💭 **Per-workspace overlays.** `~/.central-mcp/workspaces/<name>/AGENTS.md` augments the orchestrator instructions for that workspace, and a workspace-level `user.md` rides along on every dispatch inside it. Portfolio grouping is a PM concept, so these live here now (moved from the former Workspaces track).

---

## Multi-agent collaboration

**Promoted from an explicit non-goal.** The old reasoning — in-repo parallelism is the vendors' home turf — remains true for *single-vendor* teams (Claude Code agent teams, Codex multi-agent). What it missed: **cross-vendor** combinations. One agent implements, a different vendor's agent reviews — that's exactly the cross-vendor routing central-mcp already owns, applied one level deeper. No vendor team feature can do it.

📋 **Sequential role chains first.** `dispatch_chain(project, steps)` — each step names an agent and a role prompt; the previous step's output is injected into the next step's context. The canonical chain: implement (agent A) → review (agent B) → address review (agent A). Steps appear in dispatch history as linked dispatches sharing a `chain_id`; polling the chain returns per-step status. Builds almost entirely on existing dispatch plumbing, which is why it goes first.

📋 **Parallel swarm.** N agents working the same repo concurrently, isolated via git worktrees — `dispatch(..., isolation="worktree")` gives each dispatch its own checkout under `~/.central-mcp/worktrees/<project>/<dispatch_id>`. central-mcp tracks the worktree per dispatch and helps land results: merge ordering, conflict surfacing — report-and-let-the-orchestrator-decide rather than auto-merge. Phased after chains; the conflict UX is the hard part.

💭 **Role presets.** Common chains (implement→review→fix, research→implement, write-tests→implement-until-green) as named presets in `config.toml`, so a standard chain is one call with a preset name instead of a hand-built step list.

---

## Surfaces

The PM's reporting channels: the TUI control tower, live PTY panes for supervised sessions, and the watch panes in external multiplexers.

### Control tower (TUI)

The TUI's role under the new essence: the **always-on control tower** — the surface where the whole portfolio is visible at a glance and dispatch completions surface immediately (its watcher polls `dispatches.db` directly, no MCP client cooperation needed).

✅ **Phase 0 (0.12.0) — `cmcp tui --experimental`, claude only.** `textual` chrome (header / sidebar / footer / notifications), `pyte` PTY emulation, sidebar with `token_usage.summary_markdown` + active dispatches + recent completions.

✅ **Phase B (0.12.2) — codex.** Same chrome, second agent on the allowlist.

✅ **Phase C (0.14.0) — opencode + gemini.** All four orchestrators embeddable; the Phase-0 CSI leak filter covered everything the new agents emit.

📋 **Phase D — stabilization.** Self-rendered scrollback / search / copy. Korean IME and double-width corner cases. Notification policy fine-tuning (`config.toml [tui].auto_inject = passive | hint | prompt`). Feeds the 1.0 gate.

📋 **Portfolio sidebar.** Evolve the sidebar from dispatch-centric to PM-centric: per-project status lines backed by `project_pulse` (branch, last activity, next-step hint from the ledger), not just the dispatch feed.

📋 **Expanded dispatch row.** Selected row expands to a live tail of the last N output lines, elapsed, token delta, and a "last output Xs ago" health hint. Builds on `tail_dispatch` + the progress columns from the [Dispatch core](#dispatch-core-routing) track.

📋 **Reuse `token_usage.summary_markdown` in `cmcp monitor` and `cmcp watch`.** The pre-rendered HUD is currently only seen by orchestrators; wiring it into the curses monitor and the watch-pane sticky header eliminates rendering drift across surfaces.

💭 **Dispatch detail screen.** Enter on a row drills into a full-screen view: prompt / output / chain / tokens / duration / progress-marker timeline.

💭 **Heuristic progress markers.** Parse output streams for meaningful events (file writes, tool calls, test runs) into a per-dispatch badge stripe. Patterns are agent-specific, living on `agents.AGENTS` as `progress_markers`.

💭 **Watch mode: cumulative consumption next to elapsed.** `+ 42s · 8.97M tokens` instead of `+ 42s`.

💭 **Open questions.** Multi-pane inside the TUI vs. composing with an external multiplexer; how transparent prompt-injection should be (`hint` vs `prompt` mode).

### Live agent panes

Opt-in, session-scoped second execution mode, complementary to the default non-interactive dispatch. PTY mode runs the agent in a real TTY pair: permission prompts surface in a live pane the user can answer, conversation context persists across turns, and prompt-cache stays warm. The trade-off is one resident process per active project — for the 2–3 projects you're actively supervising, not the whole portfolio. Both modes share the same data model (`dispatches.db` + `dispatch.jsonl` with `mode="pty"`), so every observation surface shows both without modification.

✅ **Building blocks + session registry (0.12.2).** `PtyTerminal` doubles as a dispatch event writer (`submit_prompt` records start/complete; a screen-stability watcher flips status). `pty_sessions/<project>.json` lifecycle with stale-PID sweep, and `dispatch()` rejects calls into projects with a live PTY pane so background fan-out can't inject prompts mid-conversation.

📋 **Output capture for PTY mode.** `pyte.HistoryScreen` scrollback feeds a snapshot into `dispatches.output` on completion, closing the documented 0.12.2 gap — `check_dispatch` then returns the same shape regardless of execution mode.

📋 **`pty_inbox` queue + `pty_submit(project, prompt)` MCP tool.** Cross-process prompt routing through a small SQLite inbox; the TUI's PtyTerminal polls its own project's rows and routes them through `submit_prompt()`.

📋 **`list_projects` exposes mode.** Each row carries `mode: "pty" | "mcp"` so orchestrators pick `pty_submit` vs `dispatch` at a glance, with a matching policy line in `data/CLAUDE.md`.

💭 **Optional PTY panes in tmux / zellij / cmux layouts.** A `--mode=pty` flag or per-project override populates a pane with the project's agent CLI instead of a passive `watch` tail.

💭 **Persistent REPL conversation context.** Long-lived REPLs keep context across dispatches for free; needs a "/clear" hook or session-rotation policy against context bloat.

💭 **Permission-prompt visibility.** With a human watching the pane, agents can run *without* bypass mode: `[live].permissions = ask | bypass` per project, with `ask` being the genuinely safer choice PTY mode makes possible.

---

## Dispatch core & routing

The PM's hands: the dispatch pipeline itself, and the intelligence about where to send work. Frontier CLIs have converged on raw capability, so the interesting routing signals are cost, quota headroom, task shape, and project fit — state central-mcp already tracks.

📋 **`tail_dispatch(dispatch_id, since_ts=null)` MCP tool.** Recent output chunks since a timestamp, without waiting for completion — today `output` only fills when the subprocess exits, so nothing can show progress text mid-run without parsing `dispatch.jsonl` by hand.

📋 **`dispatches` table progress columns.** `last_output_ts`, `output_bytes`, `attempt_count` — cheap writes on every chunk; reads power the "alive vs. wedged?" indicators in every surface.

📋 **Token budgets + alerts.** Per-project / per-workspace caps in `config.toml`; threshold breaches raise a banner at dispatch start.

📋 **`suggest_dispatch(project, prompt)` MCP tool.** Returns `{agent, model, reasoning, fallback}` without dispatching — the orchestrator shows the suggestion, the user accepts or overrides. Heuristics first; an LLM-assisted classifier only if it earns its keep.

📋 **Budget-aware fallback chain.** The quota-aware chain (saved preference → fallback → remaining installed) also skips agents over their configured token budget.

📋 **Persistent session IDs.** A `sessions` table tracking each `cmcp run` instance (`id`, `workspace`, `started_at`, `pid`, `terminal_kind`), backing `cmcp sessions ls` and linking each dispatch to the session that initiated it — useful when three workspaces run concurrently.

📋 **Per-session history view.** `orchestration_history(session=<id>)` filters to one session's dispatches.

💭 **`wait_for_dispatch(dispatch_id, timeout_sec=300)` MCP tool.** Server-side blocking poll for clients that are bad at sustained polling loops. If MCP Tasks alignment lands first, Tasks-speaking clients get this natively and the tool shrinks to a shim.

💭 **`auto_dispatch` opt-in.** Combined classify + dispatch behind `[routing].auto = true` — only after `suggest_dispatch` data shows recommendations get accepted >70% of the time.

💭 **Per-workspace routing overrides.** Different favored agents per workspace (workspace `client-a` defaults to one vendor, `client-b` to another).

💭 **Agent capability registry overrides.** A `[agents.<name>]` block in `config.toml` overriding capability flags per host (e.g. mark an agent `has_quota_api = false` where its OAuth flow is broken).

---

## Ecosystem & distribution

The outward faces: protocol alignment, upstream callers that want the PM programmatically, and packaging.

### MCP Tasks alignment

The MCP 2026-07-28 release makes the protocol core stateless and promotes long-running work to an official **Tasks extension** — exactly the `dispatch` → `check_dispatch` → `cancel_dispatch` lifecycle central-mcp shipped from day one. Aligning costs little and buys native client support.

✅ **Phase 1 — task-model groundwork (0.13.0).** `tasks_adapter` translating dispatch statuses onto the Tasks lifecycle; deprecation audit (Roots / Sampling / Logging) came back clean.

✅ **Phase 2 — Tasks wire behind a flag (0.13.0).** `CENTRAL_MCP_TASKS=1` registers `tasks/get` / `tasks/cancel` / `tasks/result` backed by the same dispatch state — taskId is the dispatch_id. Flag-off default is byte-identical.

📋 **Phase 3 — migrate shape + flip the default.** When the official SDK ships the final extension model: capability advertisement, `tools/call` returning task handles, drop the flag, mechanical stateless-core conformance sweep (central-mcp is already stateless between requests by design).

### Upstream agents

Open the orchestrator to programmatic callers — personal autonomous agents that want to delegate portfolio work without a human in the REPL. Calling `dispatch` directly skips the orchestrator's routing / fallback / conflict-detection layer; these give upstream callers the full orchestrator.

✅ **Hermes Agent bridge (0.12.2–0.14.0).** `_Hermes` adapter (dispatch target *and* orchestrator), `cmcp install hermes` registering central-mcp in Hermes's config plus a bundled orchestration skill, and Hermes usage in the quota HUD. Hermes's cron + Telegram/Discord gateway is the delivery rail for the [Portfolio PM push reporting](#portfolio-pm) item.

📋 **`dispatch_orchestrator(prompt, agent=None, workspace=None)` MCP tool.** Spawns a fresh non-interactive orchestrator (claude `-p`, codex `exec`, …) loaded with central-mcp's tools; returns a `dispatch_id` mirroring `dispatch` semantics.

📋 **`cmcp ask "<prompt>"` CLI.** Synchronous shell wrapper over `dispatch_orchestrator` for upstream agents that don't speak MCP.

💭 **Per-agent non-interactive MCP-loading verification.** claude `-p` / codex `exec` are confirmed; gemini `-p` and opencode need a spike.

💭 **Persistent orchestrator session.** One long-lived orchestrator across many upstream calls — only if spawn cost proves non-negligible.

💭 **A2A endpoint.** A thin A2A server over `dispatch_orchestrator` would let any A2A-speaking agent delegate portfolio work without knowing MCP or our CLI. Gated on `dispatch_orchestrator` landing and a concrete upstream consumer existing.

💭 **Cloud agents as dispatch targets.** A `target: cloud` variant handing the prompt to a vendor's cloud backend and polling its API instead of a PID — same `dispatch_id` / `check_dispatch` contract, different executor. Needs per-vendor API stability first.

💭 **Agent-teams complement note.** A team-lead session can carry central-mcp's tools and dispatch cross-project work mid-team-session; worth a short recipe in `data/CLAUDE.md` once vendor agent teams exit experimental.

💭 **Push notifications via MCP.** The 2026-07-28 spec direction argues against it (stateless, poll-first core); kept as an idea only in case a client ships first-class notification surfacing anyway. The TUI watcher and Tasks polling remain the answers.

### Distribution

📋 **Auto-generate CLI + MCP-tool reference pages.** `scripts/gen_docs.py` walks argparse + `inspect.signature` over `server.py`; CI fails on drift.

💭 **Windows installer (PowerShell).** Pure-Python core already runs there; the friction is install + alias setup.

---

## Non-goals

Deliberate "we won't do this" — saving everyone time:

- **Browser UI.** central-mcp is terminal-native. Observation lives in the TUI, multiplexer panes, or tailed logs.
- **Agent-state syncing.** Each agent CLI owns its conversation state. The pulse *reads* session activity and git history to brief you — it never replicates or mutates agent sessions.
- **Interactive approval baked into `dispatch()`.** Default dispatch stays non-interactive (`stdin=DEVNULL`, bypass mode). Mid-run approval lives on the [Live agent panes](#live-agent-panes) track, opt-in per session.
- **Single-vendor in-repo teams.** *(Revised 2026-07 — this was previously a blanket ban on in-repo multi-agent work.)* Parallelizing one repo under one vendor's own team feature remains the vendors' turf; if you want five teammates from one vendor on one repo, run that vendor's team feature inside a dispatched session. What moved in scope is the **cross-vendor** version — role chains and worktree swarms mixing vendors — now the [Multi-agent collaboration](#multi-agent-collaboration) track.
- **Separate daemon process.** `cmcp tui` is the long-running watcher; Hermes cron covers off-terminal scheduling. No second process to install, manage, or debug.

---

## Suggesting changes

Have a use case that doesn't fit anywhere above? An idea for a new MCP tool? A "this is slowing me down every day" complaint?

→ **[Open a GitHub issue](https://github.com/andy5090/central-mcp/issues/new)** with a short description and your context (which orchestrator, which workspace, what you tried). Real usage signals shape the roadmap more than abstract phasing — one good issue often promotes a 💭 to 📋.
