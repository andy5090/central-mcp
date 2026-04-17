# Changelog

All notable changes to central-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
