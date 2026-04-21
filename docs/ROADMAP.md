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

## Phase 2b — cmux backend (macOS-only, shipped unreleased)

**Goal**: give macOS users a native-GUI option for the observation layer alongside the terminal-resident tmux / zellij backends. cmux (manaflow-ai/cmux) is an AppKit / Ghostty-based terminal with vertical tabs, notifications, and a CLI that talks to the running app over `~/.cmux/cmux.sock`.

✅ **Declarative-only surface**
- `central_mcp/cmux.py` builds a layout JSON tree and calls `cmux new-workspace --layout <json>` to open the workspace. `has_workspace` / `kill_workspace` drive the same teardown-and-rebuild contract the tmux / zellij backends already follow.
- Project panes reuse the zellij read-only wrap (`stty` off, `central-mcp watch <project>` with stdin piped from `/dev/null`, `sleep infinity` on exit) so stdin is inert and panes don't drop to a shell.
- Exposed as `central-mcp cmux` — backend-named subcommand, matching `tmux` and `zellij`. No `--max-panes` since cmux is GUI-sized; tiling reduces to ≤2 panes → single split, 3 panes → T-shape, ≥4 → 2-row grid.

✅ **Platform gating**
- `_detect_multiplexers()` includes `cmux` only when `platform.system() == "Darwin"`, so Linux / Windows users never see it offered.
- `cmd_cmux` refuses to run on non-darwin, checks the binary is on PATH, and pings the socket before attempting to open a workspace — each failure gets its own actionable error.

💭 **Explicit out-of-scope**
- Imperative RPC (`cmux send-text`, `cmux new-pane`, live layout mutation). The declarative workspace is the contract; orchestrator agents that want dynamic behavior can call `cmux` directly.
- Responsive pane-count tuning (`grid.pick_rows` / char-cell floors). cmux resizes in the GUI on its own — we don't read terminal dimensions for this backend.

---

## Phase 3 — Worker mode (interactive approval)

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

## Phase 4 — Daemon + multi-client (demand-driven)

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

## Phase 5 — MCP resource subscriptions (demand-driven)

**Goal**: expose dispatch events as first-class MCP resources so external MCP clients can subscribe without reading local log files.

💭 **Resources**
- `dispatch://<project>/events` — stream of event objects.
- `resources/subscribe` support → server pushes `notifications/resources/updated` on new events.
- Backed by the same jsonl written in Phase 1 (no schema duplication).

💭 **Depends on**
- Phase 4 (daemon + HTTP/SSE transport) — MCP resource subscriptions require a long-lived server shared across clients.

---

## Phase 6 — Workspaces (planned)

**Goal**: let users group projects into workspaces so orchestrators can address a group with one dispatch, and let a single install swap between different project sets (work / personal / client-X) without editing `registry.yaml`.

📋 **Project grouping inside a registry**
- New optional `workspace` field per project (or a top-level `workspaces: {name: [project, …]}` map).
- `dispatch("frontend", prompt)` when `frontend` is a workspace name → fan out to every project in that workspace; results aggregated or streamed per project.
- `list_projects --workspace frontend` / `orchestration_history --workspace frontend` for filtered views.
- `central-mcp up` / `cmcp zellij` can take `--workspace frontend` to bring up only that group's panes.

📋 **Registry profiles (switchable workspaces)**
- Multiple `registry.yaml` files side-by-side (e.g. `~/.central-mcp/workspaces/<name>/registry.yaml`).
- `central-mcp --workspace client-x` selects which registry + config + logs directory tree is active for the whole invocation.
- Saved default in `config.toml` under `[workspace] default = "..."`.
- Env var override: `CENTRAL_MCP_WORKSPACE=<name>`.

💭 **Shared context** (later, maybe)
- Prompts/system-instructions applied to every dispatch inside a workspace (e.g. "all these are TypeScript projects with shared style rules").
- Per-workspace `CLAUDE.md` / `AGENTS.md` templates auto-applied when launching the orchestrator for that workspace.
- Defer until 1 + 2 land and the shape of shared-state needs is clearer from real use.

💭 **Open questions**
- Resolution order when a name is both a project and a workspace — prefix rule (`@frontend` for workspace) or type disambiguation?
- Concurrent dispatch limits when fan-out grows large.
- How does orchestration_history present fan-out runs — one parent + N children, or flat list with a shared group_id?

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
- Per-workspace routing overrides (ties into Phase 6).

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
