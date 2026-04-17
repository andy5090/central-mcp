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

## Phase 2 — Zellij support (next up)

**Goal**: provide the same layout experience on Zellij for users who prefer it over tmux.

📋 **Abstract the layout backend**
- Extract a `LayoutBackend` interface from `layout.py`/`tmux.py`.
- Keep tmux backend as default, add Zellij backend.
- `central-mcp up --backend zellij` or auto-detect installed multiplexer.

📋 **Zellij implementation**
- Use Zellij's YAML layout files to declare the pane/window plan.
- Spawn via `zellij --layout <file>` or equivalent.
- Support the same orchestrator pane + window chunking semantics.

📋 **Tests**
- Zellij backend smoke tests (skip if zellij not installed, mirrors tmux skip).

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

## Non-goals / explicit decisions

- **`central-mcp install <client>` stdio setup stays the default.** Even after daemon mode lands, orchestrators continue using stdio transport for simplicity; daemon is transparent behind it.
- **No browser UI.** central-mcp is a terminal-native hub. Observation happens in tmux/zellij panes or by tailing logs.
- **No agent-state syncing.** Each agent manages its own conversation state; central-mcp only orchestrates dispatches and observes their lifecycle.

---

## Change log pointer

Actual shipped changes live in [../CHANGELOG.md](../CHANGELOG.md). This roadmap is intent, not history.
