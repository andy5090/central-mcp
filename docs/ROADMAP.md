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

💭 **Sub-feature 3 — Shared context** (deferred until 1+2 usage reveals actual needs)
- Prompts/system-instructions applied to every dispatch inside a workspace.
- Per-workspace `CLAUDE.md` / `AGENTS.md` templates auto-applied when launching the orchestrator for that workspace.

💭 **Open questions remaining**
- Concurrent dispatch cap when fan-out grows large (API rate limit exposure).
- `orchestration_history` fan-out grouping: currently flat list; `group_id` not yet implemented.
- Separate registry trees per workspace (original Sub-feature 2 design) — still useful for fully isolated client engagements.

---

## Phase 3b — User-specific instruction overlays 🚧 next

**Goal**: let central-mcp load stable user-specific operating preferences without baking personal workflow rules into the shared router contract.

📋 **Overlay model**
- Keep `AGENTS.md` as the shared project/router contract.
- Add a user-scoped overlay file for preferences such as:
  - local process management handled directly by the orchestrator,
  - project code changes still routed via dispatch,
  - reporting/language/style preferences.
- Treat the overlay as an augmentation layer, not a replacement for the core router policy.

📋 **Precedence**
- Current user turn instructions still win.
- User-specific overlay should outrank roadmap/default router preferences, but not system/developer constraints.
- Conflicts with core dispatch safety rules should resolve in favor of the shared router contract unless explicitly overridden by the user in the current turn.

📋 **Likely surface**
- Single-user first: one local file under the central-mcp home/config tree.
- Later expansion: named user profiles or structured config + free-form notes.
- Clear separation between persistent user preferences and temporary session memory (`.omx/notepad.md`).

💭 **Open questions**
- Should the first version be plain Markdown only, or structured config plus Markdown notes?
- What is the minimal precedence model that stays predictable across orchestrators?
- How should central-mcp expose the active overlay for debugging and auditability?

---

## Phase 3c — curl-based quickstart installer 📋 planned

**Goal**: let new users go from zero to a running hub in one terminal command without assuming `uv` or `pip` is already installed.

📋 **Installer script**
- Single `curl | sh` command bootstraps `uv` if missing, then runs `uv tool install central-mcp`.
- Runs `central-mcp init` to scaffold `~/.central-mcp/` and the `cmcp` alias.
- Prints a next-steps summary pointing to `central-mcp install <client>`.

📋 **Hosted at a stable URL** — short redirect (e.g. `get.central-mcp.dev`) so the quickstart stays linkable as the implementation evolves.

💭 **Open questions**
- macOS + Linux only, or attempt Windows/PowerShell parity?
- Should the script verify the installed binary version before printing success?

---

## Phase 3d — Static documentation site 📋 planned

**Goal**: provide a browsable, searchable reference beyond the README so users can find command syntax, configuration options, and examples without reading raw Markdown.

📋 **Scope**
- Generated from existing docs (`README.md`, `CHANGELOG.md`, CLI reference, MCP tool signatures).
- Covers: quickstart, CLI reference, MCP tool API, workspace guide, observation layer guide, adapter configuration.
- Hosted on GitHub Pages or equivalent; auto-deployed on each release tag.

💭 **Open questions**
- Static generator choice (VitePress, Starlight, mkdocs-material)?
- How much of the tool-signature documentation can be auto-generated from source?

---

## Phase 4 — Worker mode (interactive approval)

**Goal**: let `bypass=false` dispatches succeed when they need interactive permission prompts, by routing them through a pane-resident worker.

💭 **Opt-in, additive**: non-observation mode stays unchanged. Worker mode activates only when `central-mcp up --worker-mode` is used.

💭 **Mechanism**
- Each project pane runs `central-mcp _worker-loop <project>`.
- Worker creates `~/.central-mcp/workers/<project>.pid` + `.fifo`.
- Dispatch server checks for an alive worker before spawning:
  - Worker present → write prompt to FIFO, wait for completion signal, read result.
  - Worker dead/absent → current subprocess path (fallback).
- Output capture via `tee` to the same jsonl log from Phase 1.

💭 **Caveats**
- Serial: one dispatch per project at a time.
- Fallback needed if worker dies mid-dispatch.
- Dispatch timeout must be generous (user may be away).

---

## Phase 5 — Daemon + multi-client (demand-driven)

**Goal**: let multiple MCP clients (Claude Desktop, Codex app, CLI scripts) share one central-mcp instance and subscribe to dispatch events.

💭 **Lazy daemon**
- First MCP connection spawns a background daemon, holds PID lock at `~/.central-mcp/daemon.pid`.
- Unix socket at `~/.central-mcp/daemon.sock` (localhost TCP fallback for Windows).
- stdio `central-mcp serve` auto-detects daemon and proxies — clients keep their current config.

💭 **Commands** (power users only)
- `central-mcp daemon {start|stop|status|logs|restart}`
- `central-mcp daemon --foreground` for debugging.

💭 **Open questions**
- Auto-restart on crash? (probably no, surface error to clients)
- Version mismatch handling on upgrade (CLI vs daemon)?
- Cross-platform socket story (Windows)?

---

## Phase 6 — MCP resource subscriptions (demand-driven)

**Goal**: expose dispatch events as first-class MCP resources so external MCP clients can subscribe without reading local log files.

💭 **Resources**
- `dispatch://<project>/events` — stream of event objects.
- `resources/subscribe` support → server pushes `notifications/resources/updated` on new events.
- Backed by the same jsonl written in Phase 1 (no schema duplication).

💭 **Depends on**
- Phase 5 (daemon + HTTP/SSE transport) — MCP resource subscriptions require a long-lived server shared across clients.

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

---

## Change log pointer

Actual shipped changes live in [../CHANGELOG.md](../CHANGELOG.md). This roadmap is intent, not history.
