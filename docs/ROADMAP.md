---
description: Forward-looking plan for central-mcp — reframed around its essence as a portfolio PM. Pulse briefings, status ledger, multi-agent collaboration, reporting surfaces, dispatch core, and ecosystem alignment. Suggestions welcome via GitHub issues.
---

# Roadmap

What's planned for central-mcp. This page is **forward-looking only** — for what's already shipped, see the [Changelog](changelog.md).

> **Have a suggestion?** Open an issue at [github.com/andy5090/central-mcp/issues](https://github.com/andy5090/central-mcp/issues). We read every one.

Status legend: 📋 planned · 💭 idea · 🚧 in progress · ✅ shipped · ❌ retracted (kept so the reasoning stays on the record)

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

## The usage model — a layer, not a place

The essence section says what central-mcp is *for*; this one says *where you meet it* — ranked, because investment follows rank. Without an explicit ordering it's easy to spend the most on the surface used least; the previous roadmap did exactly that when TUI stability alone defined 1.0.

The organizing observation: **a dedicated orchestrator REPL is a destination, and a PM you have to visit gets forgotten.** The primary surface is therefore whatever agent session is already open.

**Tier 1 — ambient (the main way in): MCP tools inside the session you're already in.** Run `cmcp install claude` (or codex / gemini / opencode) once, and every session of that CLI carries `dispatch`, `project_pulse`, `orchestration_history` alongside its normal tools. The switching cost is zero: open a project, ask "where does this stand?", and the return briefing happens in place; need work done elsewhere, dispatch without leaving. Everything in the [Portfolio PM](#portfolio-pm) track lands here first.

**Tier 2 — reach: the Hermes bridge.** Every other surface assumes a human at a terminal. Hermes's cron + Telegram/Discord gateway is the one channel that finds *you* — the delivery rail for the push-reporting item (daily digest, failure alerts). For "nothing falls through the cracks" this tier ultimately matters as much as tier 1, because the most is missed precisely when no terminal is open.

**Tier 3 — focus (some days, not every day): the TUI.** For sessions whose main job *is* orchestration — fan work out across the portfolio, watch it land, supervise results. The control tower earns its screen when orchestration is the foreground task.

Two consequences, made explicit:

📋 **`cmcp run` demotes to fallback at 1.0.** The TUI is the intended tier-3 surface; `run` stays as the no-extras launcher (no `[tui]` install required) and the escape hatch for terminals that can't host textual. Demoted, not removed.

📋 **`cmcp monitor` retires into the TUI sidebar.** Quota bars + per-project dispatch counts + token sums *is* the sidebar's job description — two surfaces rendering the same data drift apart. Once the TUI is stable at 1.0, `monitor` becomes a deprecation shim pointing at `cmcp tui`; until then it stays untouched.

**Which agent hosts the orchestrator?** Orchestration is routing and narration, not coding — the binding constraint isn't model strength but discipline in the non-blocking loop (dispatch → background-poll → report). claude runs that loop reliably; codex and gemini are weak at sustained polling, which is the documented reason `wait_for_dispatch` exists on the [Dispatch core](#dispatch-core-routing) track. Recommendation until that (or native MCP Tasks clients) levels the field: **claude as the orchestrator, any agent as the dispatch target.**

---

## Portfolio PM

The new center-of-gravity track. Architecture is deliberately two-phase — **pulse first (stateless), ledger second (durable)** — so the PM's ground truth is always recomputed from the repo, and stored state is additive rather than load-bearing.

✅ **`project_pulse(project)` MCP tool + `cmcp pulse [project]` (0.15.0).** Stateless, on-demand aggregation of everything knowable about a project *right now*: git (branch, recent commits, working-tree dirt, upstream ahead/behind), dispatches (in-flight, stale, recent outcomes, counts), agent-session activity via the existing per-agent session readers, and open-PR state via `gh`. No new storage — the pulse is computed fresh on every call, so work done entirely outside central-mcp (direct commits, interactive sessions) shows up because git is the source of truth. Every section degrades independently with a `reason`, so one missing signal never sinks the pulse. This is the data spine every other PM feature stands on.

✅ **Return briefing (0.15.0).** The flagship PM moment: come back to a project after days away and get "what happened / where it stands / what's next" in one shot. Two delivery paths, both shipped — the orchestrator synthesizes a briefing from `project_pulse` whenever the user names a project (recipe in `data/{CLAUDE,AGENTS}.md`), and `cmcp pulse` with no argument sweeps the whole workspace on demand.

❌ **Retracted: `cmcp brief` as a pulse-powered digest.** Originally planned here, then measured: `brief` costs 55ms (one YAML read), a full pulse sweep costs 2.5s and spawns dozens of git processes. The SessionStart hook runs `brief` on **every** orchestrator launch, so that's a 45× tax on startup — and most of it is discarded work, because you open a session to touch one or two projects, not seventeen. The right split is that session start says cheaply *what exists*, and *what state it's in* is fetched the moment the user names a project. Both halves now exist, so `brief` stays a registry listing.

📋 **Status ledger (phase 2).** `~/.central-mcp/projects/<name>/STATUS.md` — durable per-project memory: a structured delta appended when a dispatch completes (what was done, what was left), open questions, and a "next steps" list that survives across sessions and orchestrators. `cmcp note <project> "…"` adds manual entries. Briefings then combine ledger (intent, next steps) with pulse (ground truth) and flag drift between the two. Plain files, same as the registry — the stateless-between-requests invariant holds.

✅ **Push reporting (0.17.0).** Daily/weekly digests and event alerts delivered without a new daemon. `portfolio_digest` renders a fixed-format, pulse-powered report server-side (`digest_markdown`, forwarded verbatim — same reasoning as `token_usage.summary_markdown`); `cmcp digest` serves the same report to plain crontabs. `list_dispatches(status="failed", since=…)` gives resident agents a re-alert-proof failure cursor whose watermark lives with the subscriber, keeping central-mcp stateless. The Hermes skill's sketch is now two first-class recipes (daily digest cron, failure watch); the TUI watcher remains the local surface.

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

Two different jobs have always been filed together under "observation", and separating them is what this track is now organized around.

A **map** answers *where is everything?* — the whole portfolio at a glance, a line per project. `cmcp pulse`, the TUI sidebar, and the orchestrator's briefing are maps.

A **microscope** answers *what is this one thing doing right now?* — raw, live, unsummarized. `cmcp watch`, an expanded dispatch row, and a live PTY pane are microscopes.

A better map never removes the need for a microscope, for two reasons. Asking the orchestrator costs a turn, tokens, and a context switch, while a pane in your peripheral vision costs nothing — ambient awareness is a different thing from a request/response loop. And more fundamentally, a narrated pulse is *an LLM summarizing*: when an agent reports "tests pass", sometimes you need the actual test output. A better summary is still a summary. That gap is categorical, not a missing feature — and it matters more, not less, in a system where dispatches run unattended in bypass mode.

What went wrong historically was applying the microscope at map scale. `cmcp tmux` tiled one watch pane per registered project, so on a large portfolio most panes sat dead and the one worth reading was three windows away. The map job now has proper owners, so the grid goes back to being focused.

### Control tower (TUI) — the map

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

### Focused panes — the microscope

`cmcp watch <project>` tails a project's `dispatch.jsonl` and renders each event live. Its role is now stated plainly: **a live window on the one dispatch you care about**, not a portfolio surface. Ground truth, unsummarized, free to glance at.

✅ **Observation panes default to focus (0.16.0).** `cmcp up` / `tmux` / `zellij` no longer tile every registered project. When the workspace fits in one window nothing changes; past that they open panes for the most recently active projects that do fit, and print what was left out plus how to get it. `--projects a,b,c` picks explicitly, `--all-projects` restores full tiling. Activity ranking reuses the pulse signals (`pulse.rank_by_activity`), so "most recent" means real work — git commits included — not just dispatch traffic.

📋 **Live output inside the TUI.** The sidebar can show a running dispatch's output as it arrives; the data has been there all along. `dispatch()`'s reader threads already write one `output` event per line into `dispatch.jsonl` in real time — that is exactly what `watch` renders — but `DispatchWatcher` polls `dispatches.db`, whose `output` column is only written when the process exits. So the TUI is blind mid-run because it watches the wrong file, not because the output is hard to obtain. `watch._tail_forever` already implements the offset-based tail with truncation handling that this needs.

> This is worth stating explicitly because it has been conflated with a genuinely hard problem: **PTY-mode output capture** (below) has no per-chunk event stream at all, since reconstructing structured chunks from a raw ANSI screen is the actual difficulty. The two are unrelated. The MCP-dispatch case is wiring; the PTY case is a research question.

📋 **`tail_dispatch` as the shared encapsulation.** Rather than teaching each surface to parse jsonl, the [Dispatch core](#dispatch-core-routing) track's `tail_dispatch` tool gives orchestrators, the TUI sidebar, and anything else one supported way to ask "what has this dispatch emitted since T?".

### Live agent panes

Opt-in, session-scoped second execution mode, complementary to the default non-interactive dispatch. PTY mode runs the agent in a real TTY pair: permission prompts surface in a live pane the user can answer, conversation context persists across turns, and prompt-cache stays warm. The trade-off is one resident process per active project — for the 2–3 projects you're actively supervising, not the whole portfolio. Both modes share the same data model (`dispatches.db` + `dispatch.jsonl` with `mode="pty"`), so every observation surface shows both without modification.

✅ **Building blocks + session registry (0.12.2).** `PtyTerminal` doubles as a dispatch event writer (`submit_prompt` records start/complete; a screen-stability watcher flips status). `pty_sessions/<project>.json` lifecycle with stale-PID sweep, and `dispatch()` rejects calls into projects with a live PTY pane so background fan-out can't inject prompts mid-conversation.

📋 **Output capture for PTY mode.** The genuinely hard one, and the source of the 0.12.2 deferral note. A PTY-hosted agent produces a repainting ANSI screen, not a line stream, so there is no per-chunk `output` event to record and no clean text to store — deriving either means reconstructing structure from terminal escape sequences. First step is the cheap approximation: snapshot `pyte.HistoryScreen`'s scrollback into `dispatches.output` on completion so `check_dispatch` returns the same shape regardless of execution mode. Live per-chunk events for PTY mode stay open.

📋 **`pty_inbox` queue + `pty_submit(project, prompt)` MCP tool.** Cross-process prompt routing through a small SQLite inbox; the TUI's PtyTerminal polls its own project's rows and routes them through `submit_prompt()`.

📋 **`list_projects` exposes mode.** Each row carries `mode: "pty" | "mcp"` so orchestrators pick `pty_submit` vs `dispatch` at a glance, with a matching policy line in `data/CLAUDE.md`.

💭 **Optional PTY panes in tmux / zellij / cmux layouts.** A `--mode=pty` flag or per-project override populates a pane with the project's agent CLI instead of a passive `watch` tail.

💭 **Persistent REPL conversation context.** Long-lived REPLs keep context across dispatches for free; needs a "/clear" hook or session-rotation policy against context bloat.

💭 **Permission-prompt visibility.** With a human watching the pane, agents can run *without* bypass mode: `[live].permissions = ask | bypass` per project, with `ask` being the genuinely safer choice PTY mode makes possible.

---

## Dispatch core & routing

The PM's hands: the dispatch pipeline itself, and the intelligence about where to send work. Frontier CLIs have converged on raw capability, so the interesting routing signals are cost, quota headroom, task shape, and project fit — state central-mcp already tracks.

📋 **`tail_dispatch(dispatch_id, since_ts=null)` MCP tool.** Recent output chunks since a timestamp, without waiting for completion. `dispatches.db`'s `output` column is only written when the subprocess exits, so every surface that wants mid-run progress has to parse `dispatch.jsonl` itself — where the per-line `output` events have been landing in real time since long before the TUI existed. This tool makes that one supported path instead of three ad-hoc readers. See [Focused panes](#focused-panes-the-microscope) for why this is wiring rather than a hard problem.

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
