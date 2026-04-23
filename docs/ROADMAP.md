# Roadmap

Planned direction for central-mcp. Ordered by priority; later phases depend on demand.

Status legend: ✅ done · 🚧 in progress · 📋 planned · 💭 idea

---

## Phase 1 — Observable dispatch (shipped in 0.2.0)

**Goal**: make `central-mcp up` actually observable. Every dispatch writes structured events to a per-project log; panes stream those events live.

✅ **jsonl event log**
- Path: `~/.central-mcp/logs/<project>/dispatch.jsonl` (append-only JSON Lines).
- Events: `start`, `attempt_start`, `output` (line-oriented chunks), `complete`, `error`.
- `server.py dispatch()` streams subprocess stdout/stderr into the jsonl via reader threads while still returning the full response as the MCP result.

✅ **`central-mcp watch <project>` CLI**
- Tails the project's jsonl with human-readable formatting (ANSI colors, headers, exit code, duration).
- Touches the log file if missing so fresh projects wait silently for the first dispatch.

✅ **tmux pane integration**
- Project panes run `central-mcp watch <project>`; orchestrator pane stays interactive.
- Hub window uses `main-vertical` with `main-pane-width 50%` so the orchestrator takes the left half; overflow projects chunk into `cmcp-2`, `cmcp-3`, … with the first window picking up a `-hub` suffix.
- Pane border titles + conditional `pane-border-format` highlight the orchestrator in bold yellow.

✅ **Tests**
- Dispatch event sequence end-to-end, watch renderer unit tests, layout invariants (main-vertical coordinates, window/pane counts, active-pane focus).

✅ **Related quality-of-life shipped alongside**
- Default bypass flipped to ON with a README risk disclaimer (`--no-bypass` opts out).
- `central-mcp tmux` one-shot (create-if-missing + attach) named after the backend so `central-mcp zellij` can sit beside it in Phase 2.
- `central-mcp upgrade` for PyPI-driven self-update (0.2.1).
- `codex` / `gemini` adapters now resume the last session (`codex exec resume --last`, `gemini --resume latest`).

---

## Phase 2 — Zellij support (shipped, unreleased)

**Goal**: provide the same layout experience on Zellij for users who prefer it over tmux.

✅ **Zellij implementation**
- New `central_mcp/zellij.py` builds a KDL layout for the current registry and launches (or attaches to) a session named `central`.
- Same chunking / hub / pane-title semantics as tmux mode; project panes run `central-mcp watch <project>`.
- Exposed as `central-mcp zellij` — backend-named subcommand, matching `central-mcp tmux`.

✅ **Tests**
- Unit tests for KDL generation across empty registry / orchestrator present / absent / overflow. Live validation deferred to manual usage because zellij needs a TTY.

💭 **Deferred**
- `LayoutBackend` interface extraction. Kept the two modules independent for now — duplication is mild, and a single abstraction is easier to design after a third backend appears (or a real pain point shows up).
- Auto-detect mode (`central-mcp up --backend auto`). Explicit picks (`tmux` / `zellij`) keep the contract obvious.

---

## Phase 2b — cmux (macOS, agent-driven only — no CLI surface)

**Goal**: let macOS users get the observation layer via [cmux.app](https://github.com/manaflow-ai/cmux) without adding a brittle CLI wrapper. cmux is a native GUI terminal designed so that agents manage their own panes (it injects `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID` into every pane it spawns), so the orchestrator agent handles observation-pane setup directly.

✅ **Agent-driven workflow (no dedicated CLI command)**
- Open cmux.app, run `cmcp` in a pane to launch the configured orchestrator, then ask the orchestrator to set up observation panes. The orchestrator reads `src/central_mcp/data/AGENTS.md` (shipped to `~/.central-mcp/AGENTS.md` at hub init) which includes a "Running inside cmux" section covering the exact cmux CLI incantations (`cmux new-split` → `cmux --json list-pane-surfaces` → `cmux send-text`). On `CMUX_WORKSPACE_ID` absence the section is a no-op, so the same guideline file is safe across tmux / zellij / cmux contexts.

💭 **Why no CLI command**
- An earlier 0.8.0 attempt shipped `central-mcp cmux` that spawned a workspace via `cmux new-workspace --command 'claude "<seed prompt>"'`. Long seed payloads (1k+ chars) proved fragile — cmux's keystroke-injection truncated mid-string in the wild, and shell quoting races made the launch unreliable. Delegating to the agent's Bash tool avoids both failure modes: command lengths stay small, no shell inside the cmux pane, the agent sees each cmux CLI call's output and can retry per-project on failure.

💭 **Declarative layout (future path)**
- cmux source has `--layout <json>` wired up on `new-workspace`, but it hasn't landed in a shipped release (0.63.2 rejects the flag). If a future release exposes it, central-mcp could add back a "build the whole layout up front" path as a parallel option, without removing the agent-driven flow.

⚠️ **Scope**
- opencode / droid are supported like any other orchestrator on the tmux / zellij backends. Inside cmux, any agent whose Bash tool can execute `cmux new-split` will work — the AGENTS.md section is agent-agnostic.

---

## Phase 3 — Workspaces ✅ shipped in 0.9.x

**Goal**: let users group projects into named workspaces so orchestrators can address a group with one dispatch, and swap between different project sets without editing `registry.yaml`.

Design spec: [`docs/architecture/workspaces.md`](architecture/workspaces.md)

✅ **Sub-feature 1 — Project grouping inside a registry (0.9.0)**
- Top-level `workspaces: {name: [project, …]}` map in `registry.yaml`; `current_workspace` field tracks the active workspace. Auto-migrated on first use.
- `dispatch("@workspace", prompt)` fans out to every project in the workspace; returns a list of `dispatch_id`s.
- `list_projects(workspace=...)` / `orchestration_history(workspace=...)` for filtered views.
- `add_project(…, workspace=...)` registers a project and assigns it in one call.
- `cmcp tmux` / `cmcp zellij` accept `--workspace NAME`, `--all`, and `switch NAME`; sessions named `cmcp-<workspace>`.

✅ **Sub-feature 2 — Active workspace switching (0.9.0)**
- `cmcp workspace list / current / new / use / add / remove` CLI subcommand tree.
- Active workspace stored in `registry.yaml` as `current_workspace`. Simpler than the originally-planned separate registry trees per workspace; separate-tree model deferred.

✅ **Migration fix (0.9.2)**
- On first migration of a pre-workspace registry, `default` is now seeded with all existing project names so the YAML reflects reality. `add_to_workspace` to a named workspace removes the project from `default` to avoid duplicate membership.

✅ **`current_workspace` moved to config.toml (0.10.0)**
- Per-user UI state, not shared project metadata — it lives in `config.toml [user].current_workspace` now, alongside `[user].timezone` and `[orchestrator].default`. One-shot migration on startup lifts any legacy `current_workspace` key out of `registry.yaml`.

✅ **`list_projects()` scopes to current workspace by default (0.10.1)**
- Calling the tool with no args returns the user's *current* workspace instead of every registered project across workspaces — matches orchestrator intuition ("what am I working on right now"). Opt into the old behavior with `workspace="__all__"` (canonical) or `workspace="*"` (alias).

💭 **Sub-feature 3 — Shared context** (deferred until 1+2 usage reveals actual needs)
- Prompts/system-instructions applied to every dispatch inside a workspace.
- Per-workspace `CLAUDE.md` / `AGENTS.md` templates auto-applied when launching the orchestrator for that workspace.

💭 **Open questions remaining**
- Concurrent dispatch cap when fan-out grows large (API rate limit exposure).
- `orchestration_history` fan-out grouping: currently flat list; `group_id` not yet implemented.
- Separate registry trees per workspace (original Sub-feature 2 design) — still useful for fully isolated client engagements.

---

## Phase 4 — UX & personalization ✅ largely shipped in 0.10.x

**Goal**: make central-mcp more tailored to individual users and more observable at a glance — covering personal workflow rules, watch-pane readability, and usage visibility.

✅ **User-specific instruction overlays** (shipped 0.9.4)
- `~/.central-mcp/user.md` scaffolded on first launch; orchestrators read it at session start.
- Augmentation layer — outranks router defaults but not system/developer constraints; user turn instructions still win.
- Never overwritten by upgrades. Single-user; named profiles deferred.

✅ **Watch mode visual improvements** (shipped 0.9.4 → refined through 0.9.x)
- Elapsed time prefix (`+  42s`) on every output line during active dispatch.
- Code block detection (` ``` ` / `~~~` fences) → magenta to separate prose from code.
- Spinner / progress-bar / blank lines dimmed to reduce visual clutter; agent-specific noise filtering (Codex headers, Gemini warnings).
- Fallback `attempt_start` transitions rendered in yellow with `↻` arrow.
- Curses sticky header keeps project / agent / status pinned while the log scrolls below.

✅ **Token usage monitoring — full backend rebuild** (shipped 0.10.0)
- **Adapter-driven JSON-output parsing** replaces the 0.9.4 regex path (which matched 0% in practice because agent CLIs don't emit tokens in plain stdout). Each adapter's `exec_argv` now requests structured output (`claude --output-format json`, `codex --json`, `gemini -o json`, `droid -o json`, `opencode --format json`) and its `parse_output(stdout)` returns `(display_text, {input, output, total})` deterministically. Gemini aggregates across router + main models per request.
- **`~/.central-mcp/tokens.db` SQLite aggregation store** — single flat `usage` table, `UNIQUE(source, session_id, request_id)` making re-syncs idempotent. `source` is either `dispatch` (subprocess) or `orchestrator` (session-file derived).
- **Orchestrator-session token backfill** — `dispatch()` scans the active orchestrator's session file on every call and records per-turn tokens (Claude Code: `~/.claude/projects/<slug>/*.jsonl`; Codex: `~/.codex/sessions/**/rollout-*.jsonl`). Gemini has no on-disk session store → no-op; opencode (SQLite-backed) is a Phase 4.1 follow-up.
- All reads windowed by `config.toml [user].timezone`, auto-seeded with the system IANA name on install/upgrade.

✅ **`token_usage` MCP tool** (shipped 0.10.0)
- Portfolio-wide aggregation split out from `orchestration_history` so event history and token accounting evolve independently. Parameters: `period` (`today`/`week`/`month`/`all`), `project`, `workspace`, `group_by` (`project`/`agent`/`source`). Paves the way for a live token pane.

✅ **`central-mcp monitor` portfolio dashboard** (shipped 0.10.0)
- Curses live view. Top: per-agent subscription quota bars (Claude Pro 5h/wk, Codex ChatGPT 1h/day) polled from provider OAuth usage APIs; Gemini shows auth type only. Bottom: DISPATCH STATS with `today tok` / `7d tok` columns.
- Quota refreshes every 90s in a background thread; stats every 10s.

✅ **Timeline rotation + archive summaries** (shipped 0.10.0)
- `log_timeline()` opportunistically rotates `timeline.jsonl` (>5 MB or >10k lines) into `archive/timeline-<utc-microsecond>.jsonl` + paired `*-summary.json` (per-project event counts, per-agent events, `{from, to}` ts range). Dormant at today's install sizes — infrastructure in place for long-running deployments.
- `orchestration_history(include_archives=True)` attaches archive summaries (not raw records) so callers can see the full shape of history without blowing past context.

✅ **Concurrency correctness** (shipped 0.10.0)
- `log_timeline()` serialized with `threading.Lock` + `fcntl.flock` (POSIX). File line order now tracks `ts` order under concurrent writers (MCP handler thread + multiple `_run_bg` daemon threads). Windows native gracefully degrades to `threading.Lock` only.

✅ **User config consolidation** (shipped 0.10.0)
- New `central_mcp.config` module owns `~/.central-mcp/config.toml`. Sections: `[orchestrator].default`, `[user].timezone`, `[user].current_workspace`.

✅ **Arrow-key interactive pickers** (shipped 0.10.2)
- `central-mcp run` (orchestrator choice) and `central-mcp up` (multiplexer choice) use ↑/↓ (or k/j) navigation with a bold highlight + cursor-hide during selection. Non-TTY environments (piped stdin, Windows native) transparently fall back to the legacy numbered prompt.

📋 **Token budget + alerting** (Phase 4.1, next)
- Running cumulative token / cost tracker per project and per workspace (configurable cap). tokens.db + `token_usage` tool provide the primitives; budget policy + UI alerts still to land.
- Watch mode shows cumulative consumption alongside elapsed time.

📋 **opencode orchestrator-session backfill** (Phase 4.1)
- `orch_session` currently supports claude + codex via filesystem JSONL; opencode's SQLite-backed sessions need a dedicated reader.

💭 **Open questions**
- Full syntax highlighting (`pygments`/`rich`) or extend current heuristics?
- Token budget: stored in `registry.yaml` per project, or separate `budget.yaml`?
- Named user profiles (defer until demand is clear).

---

## Phase 5 — Distribution & docs 📋 planned

**Goal**: make it trivially easy for new users to discover, install, and understand central-mcp.

📋 **curl-based quickstart installer**
- Single `curl | sh` command bootstraps `uv` if missing, then runs `uv tool install central-mcp`.
- Runs `central-mcp init` to scaffold `~/.central-mcp/` and the `cmcp` alias.
- Hosted at a stable short URL (e.g. `get.central-mcp.dev`).

📋 **Static documentation site**
- Generated from existing docs (`README.md`, `CHANGELOG.md`, CLI reference, MCP tool signatures).
- Covers: quickstart, CLI reference, MCP tool API, workspace guide, observation layer guide, adapter configuration.
- Hosted on GitHub Pages or equivalent; auto-deployed on each release tag.

💭 **Open questions**
- macOS + Linux only for the installer, or attempt Windows/PowerShell parity?
- Static generator choice (VitePress, Starlight, mkdocs-material)?
- How much of the tool-signature documentation can be auto-generated from source?

---

## Phase 6 — Daemon + push notifications (demand-driven)

**Goal**: let multiple MCP clients share one central-mcp instance and receive dispatch completions via push rather than polling.

💭 **Lazy daemon**
- First MCP connection spawns a background daemon, holds PID lock at `~/.central-mcp/daemon.pid`.
- Unix socket at `~/.central-mcp/daemon.sock` (localhost TCP fallback for Windows).
- stdio `central-mcp serve` auto-detects daemon and proxies — clients keep their current config.

💭 **MCP resource subscriptions**
- `dispatch://<project>/events` — stream of event objects.
- `resources/subscribe` support → server pushes `notifications/resources/updated` on completion.
- Backed by the same jsonl written in Phase 1 (no schema duplication).
- Eliminates background polling loops in orchestrators; any agent gets completions automatically.

💭 **Commands** (power users only)
- `central-mcp daemon {start|stop|status|logs|restart}`
- `central-mcp daemon --foreground` for debugging.

💭 **Open questions**
- Auto-restart on crash? (probably no, surface error to clients)
- Version mismatch handling on upgrade (CLI vs daemon)?
- Cross-platform socket story (Windows)?

---

## Phase 7 — Agent harness (smart routing)

**Goal**: act as a higher-level agent harness — given a user request, automatically pick the best coding agent and model tier for the job, then dispatch accordingly. The orchestrator stops making routing decisions itself; it just passes the task to central-mcp and trusts the harness to choose.

📋 **Task classifier**
- New MCP tool `suggest_dispatch(project, prompt)` — returns `{agent, model, reasoning, fallback}` without dispatching. The orchestrator can show the suggestion, call `dispatch` with it, or override.
- Optional `auto_dispatch(project, prompt)` — classify + dispatch in one shot.
- Heuristics at first (prompt length, keywords: "refactor", "research", "summarize", "shell command", "review", etc.), with an optional LLM-assisted classifier as a follow-up.

📋 **Agent capability registry**
- Structured metadata per agent: strengths (reasoning depth, tool use, speed), known weaknesses, cost tier, model tiers available.
- Seeded with defaults for claude / codex / gemini / droid / opencode; user can override in `config.toml` under `[agents.<name>]`.
- Model tier selection: each agent exposes low / medium / high variants, and the harness picks based on task complexity heuristics.

📋 **Routing config**
- `config.toml` under `[routing]` for preferences: favored agent for code-heavy tasks, fallback chains, cost caps.
- Per-workspace routing overrides (ties into Phase 3 — Workspaces).

💭 **Open questions**
- How much of this belongs in central-mcp vs. a purpose-built classifier sidecar?
- Do we expose the classifier's reasoning in MCP responses for auditability?
- Should `auto_dispatch` be opt-in only, or become the default once good enough?

---

## Non-goals / explicit decisions

- **`central-mcp install <client>` stdio setup stays the default.** Even after daemon mode lands, orchestrators continue using stdio transport for simplicity; daemon is transparent behind it.
- **No browser UI.** central-mcp is a terminal-native hub. Observation happens in tmux/zellij panes or by tailing logs.
- **No agent-state syncing.** Each agent manages its own conversation state; central-mcp only orchestrates dispatches and observes their lifecycle.
- **No interactive approval / worker mode.** Dispatch is non-interactive by design. If a user needs to approve actions mid-run, they should run the agent directly in a terminal — that's outside central-mcp's scope.

---

## Change log pointer

Actual shipped changes live in [../CHANGELOG.md](../CHANGELOG.md). This roadmap is intent, not history.
