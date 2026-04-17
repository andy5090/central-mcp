# Changelog

All notable changes to central-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Dispatch event log: every dispatch streams `start` / `output` / `complete` events to `~/.central-mcp/logs/<project>/dispatch.jsonl`
- `central-mcp watch <project>` — human-readable live tail of the event log (ANSI-colored headers, exit code, duration)
- `central-mcp up` runs `central-mcp watch <project>` in each project pane so dispatch activity is visible
- `central-mcp up`: orchestrator pane at pane 0 (auto-picks saved run preference; `--no-orchestrator` opts out, `--bypass` applies permission-skip flag)
- `central-mcp up --panes-per-window N` (default 4) chunks panes across `cmcp-1`, `cmcp-2`, … so registries of any size fit. The first window gets a `-hub` suffix (`cmcp-1-hub`) when it contains the orchestrator.
- `codex` and `gemini` adapters now support session resume (`codex exec resume --last`, `gemini --resume latest`)

### Changed
- Dispatch subprocess stdout/stderr are now read line-by-line so they can be streamed into the event log while still returning the full output in the MCP response
- `central-mcp up` layout re-tiles after every split and focuses pane 0 so attaching users land on the orchestrator

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
