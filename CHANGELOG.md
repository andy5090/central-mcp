# Changelog

All notable changes to central-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.1] — 2026-04-18

### Added
- Cold-start auto-bootstrap: `central-mcp` on first run now auto-creates `~/.central-mcp/registry.yaml` and registers central-mcp with every MCP client binary it detects on PATH (claude / codex / gemini / opencode). A marker file (`.install_auto_done`) makes it idempotent on subsequent launches.
- `central-mcp install all` — explicit "detect + register everywhere" command. Individual `central-mcp install <client>` still available for fine-grained control.

## [0.3.0] — 2026-04-18

### Added
- `orchestration_history(n, window_minutes)` MCP tool — portfolio-wide snapshot (in-flight dispatches + recent cross-project milestones + per-project counts + registry). Purpose-built so orchestrators can answer "how is everything going?" in a single call.
- Global `~/.central-mcp/timeline.jsonl` — compact chronological milestone log (`dispatched` / `complete` / `error` / `cancelled`) across all projects.
- Live E2E test for `orchestration_history` (gated behind `pytest -m live`).

### Changed
- **Breaking**: `dispatch_history` now requires a `name` argument and reads terminal events (merged with their `start`) from `~/.central-mcp/logs/<project>/dispatch.jsonl` — no separate per-project summary file needed. Use `orchestration_history` for cross-project views.

### Removed
- `~/.central-mcp/history/<project>.jsonl` is no longer written. Historical data is derived from the live event log (per project) and timeline (global). Existing history files from 0.2.x installs are untouched but unused — delete or archive them if desired.

## [0.2.1] — 2026-04-18

### Added
- `central-mcp upgrade` — checks PyPI for a newer release and runs `uv tool install --reinstall --refresh central-mcp` (or `pip install --upgrade` when uv isn't on PATH). `--check` just queries without installing.

## [0.2.0] — 2026-04-18

### Added
- Dispatch event log: every dispatch streams `start` / `output` / `complete` events to `~/.central-mcp/logs/<project>/dispatch.jsonl`
- `central-mcp watch <project>` — human-readable live tail of the event log (ANSI-colored headers, exit code, duration)
- `central-mcp up` runs `central-mcp watch <project>` in each project pane so dispatch activity is visible
- `central-mcp up`: orchestrator pane at pane 0 (auto-picks saved run preference; `--no-orchestrator` opts out)
- Hub window uses `main-vertical` layout with `main-pane-width 50%` so the orchestrator takes the left half and project panes stack on the right
- Pane border titles + conditional `pane-border-format` highlighting the orchestrator pane in bold yellow
- `central-mcp tmux` subcommand — one-shot: creates the observation session if missing, then attaches via tmux (named after the backend so `central-mcp zellij` can sit next to it in Phase 2)
- `central-mcp up --panes-per-window N` (default 4) chunks panes across `cmcp-1`, `cmcp-2`, … so registries of any size fit. The first window gets a `-hub` suffix (`cmcp-1-hub`) when it contains the orchestrator.
- `codex` and `gemini` adapters now support session resume (`codex exec resume --last`, `gemini --resume latest`)

### Changed
- **Bypass is now ON by default** for `central-mcp run` / `central-mcp up` — central-mcp is a non-stop orchestration hub; permission prompts stall dispatches since there's no one to answer them. Pass `--no-bypass` to opt out. README carries a risk warning + liability disclaimer.
- Dispatch subprocess stdout/stderr are now read line-by-line so they can be streamed into the event log while still returning the full output in the MCP response
- `central-mcp up` layout re-tiles after every split and focuses pane 0 so attaching users land on the orchestrator
- Hub window: `panes_per_window - 1` panes (orchestrator visually takes 2 cells via main-vertical); overflow windows get the full `panes_per_window`

### Removed
- `central-mcp up --interactive-panes` (legacy per-project interactive agent mode). Run the agent directly in a regular terminal if you need interactive access.

## [0.1.2] — 2026-04-17

### Added
- `-v` / `--version` flag
- `central-mcp --bypass` / `--pick` / `--agent` work without typing `run`

## [0.1.1] — 2026-04-17

### Added
- `opencode` orchestrator support: `central-mcp install opencode` patches `~/.config/opencode/opencode.json`
- `central-mcp` / `cmcp` with no arguments now launches the orchestrator (was: MCP stdio server)
- Open-source scaffolding: CHANGELOG, CONTRIBUTING, GitHub issue templates, PyPI badges

## [0.1.0] — 2026-04-17

First public release on PyPI.

### Added
- `opencode` as a supported dispatch agent and orchestrator (`opencode run --continue --dangerously-skip-permissions`)
- `central-mcp install opencode` — patches `~/.config/opencode/opencode.json`
- `central-mcp install gemini` — patches `~/.gemini/settings.json`
- Per-dispatch agent override: `dispatch(name, prompt, agent="codex")`
- Fallback chain on failure: `dispatch(name, prompt, fallback=["codex", "gemini"])`
- `update_project` MCP tool — change agent, description, tags, bypass, fallback
- `dispatch_history` MCP tool — persistent JSONL log survives server restarts
- `cancel_dispatch` MCP tool — abort a running dispatch
- Live CLI contract tests (`pytest -m live`) — verify adapter flags against real `--help` output
- Live dispatch E2E tests — full roundtrip: `dispatch()` → subprocess → `check_dispatch()`
- `central-mcp run --pick` / `--bypass` / `--agent` orchestrator launch flags

### Changed
- `shell` agent removed — every registered project must be dispatchable non-interactively
- `amp` agent removed — Amp Free rejects non-interactive execute mode
- `droid` adapter: removed erroneous `-r` (was `--reasoning-effort`, not resume)
- Bypass flag resolved before dispatch probe, not after
- `cancel_dispatch` acquires lock atomically; cancellation propagates through fallback chain

### Fixed
- Security: synthetic test tokens in `test_scrub.py` split across string literals to prevent secret scanner false positives

## [0.0.x] — pre-release

- Initial scaffold: adapters (claude, codex, gemini, droid), registry-driven tmux layout
- Non-blocking dispatch with background thread stdout capture
- `check_dispatch` / `list_dispatches` polling tools
- `add_project` / `remove_project` MCP tools with agent validation
- Per-project bypass mode (saved to registry)
- `central-mcp install claude` / `codex` — MCP client auto-registration
- Optional tmux observation layer (`central-mcp up` / `down`)
- Registry cascade: env var → cwd → `~/.central-mcp/registry.yaml`
- Output scrubbing (ANSI, secrets) on dispatch results
