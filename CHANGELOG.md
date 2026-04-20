# Changelog

All notable changes to central-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.6.1] — 2026-04-20

### Added
- **Observation-session version stamp.** `cmcp up` / `cmcp tmux` / `cmcp zellij` now write `~/.central-mcp/session-info.toml` with the central-mcp version that built the session. On every subsequent attach, the stamp is compared to the currently-installed version; when they diverge the command refuses to attach and prints a warning pointing at `cmcp down`. Guards against a common post-upgrade failure mode where panes keep running the previous version's orchestrator + watch processes and stop picking up new events, updated argv flags, or refreshed instruction files.
- **`--force-recreate` flag** on `cmcp up` / `cmcp tmux` / `cmcp zellij` — tears down the existing session (both backends, plus the stamp file) and rebuilds in a single step instead of requiring a manual `cmcp down && cmcp zellij`.
- README / README_KO: new "Upgrading while an observation session is attached" subsection under the observation-layer docs, explaining the stale-process problem, the guard, and the two recovery paths. Explicitly framed as "only matters if you use observation mode" so dispatch-only workflows skip it.

### Internal
- New `central_mcp.session_info` module encapsulates read / write / clear / `staleness_warning` logic with a `SessionStamp` dataclass. Covered by 8 unit tests (round-trip, malformed file tolerance, mismatch detection, mismatch-message contents).

## [0.6.0] — 2026-04-20

### Added
- **Per-project session resumption with `session_id`** on every dispatch. Each agent now maps `session_id` to its own specific-session flag (claude `-r <uuid>`, codex `resume <uuid>`, gemini `--resume <index>`, droid `-s <uuid>`, opencode `-s <uuid>`). Resolution order: explicit `dispatch(session_id=...)` argument → project's saved pin → agent's default resume-latest flag.
- **New MCP tool `list_project_sessions(name, limit=20)`** — enumerates the agent's resumable conversation sessions scoped to the project's cwd. Adapters implement discovery via filesystem scan (claude, codex, droid — read `~/.claude/projects/<slug>/`, `~/.codex/sessions/**/`, `~/.factory/sessions/<slug>/`) or subprocess call (gemini `--list-sessions`, opencode `session list`). Returns `id`, optional `title`, and `modified` (ISO 8601). Response echoes `pinned` so the orchestrator can mark the currently-locked session.
- **`session_id` on `update_project`** — persist a pin so future dispatches always carry the specific-session flag, immune to ambient drift from interactive sessions sharing the cwd. Pass `session_id=""` (empty string) to clear.
- **Orchestrator session-handling guidelines in `data/CLAUDE.md` / `data/AGENTS.md`** — when the user asks about "other sessions", `list_project_sessions`; when they want a one-shot switch, `dispatch(session_id=...)`; when they want drift-proof continuity (required for droid), `update_project(session_id=...)`.

### Notes
- **One-shot switch is usually enough.** For claude/codex/gemini/opencode, passing `session_id` to `dispatch` once is sufficient — the agent's own "resume latest" mechanism picks up the just-used session on subsequent default dispatches. Registry pinning is only needed when ambient state might drift (interactive sessions in the same cwd) or when the agent has no resume-latest.
- **Droid exception.** `droid exec` has no headless "resume latest" — every dispatch without an explicit `session_id` is a fresh thread. To get continuity across droid dispatches, either pass `session_id` each time or `update_project(session_id=...)` to pin.
- **Gemini caveat.** Gemini uses 1-based numeric session indexes (not UUIDs). Indexes shift when new sessions are added; treat them as momentary references rather than stable identifiers.
- **Opencode caveat.** `opencode session list` returns sessions globally (not cwd-scoped). The candidate list is still useful for pin selection but may include sessions from other directories.

### Upgrading
- Adapter implementations outside this repo must add a `session_id: str | None = None` kwarg to `exec_argv`. Omitting it will raise `TypeError: got an unexpected keyword argument` when central-mcp dispatches to that adapter.

## [0.5.2] — 2026-04-19

### Added
- **`output_preview` on every dispatch history record.** Each terminal event and timeline milestone now carries a 300-char tail of the agent's final stdout, so `dispatch_history` and `orchestration_history` can power per-project "what was done + what came out" summaries without fanning out to the raw jsonl logs. Preview is ellipsis-prefixed when truncated; short outputs pass through verbatim. Inherits the existing `scrub()` secret-redaction pipeline.
- **Soft guidelines in orchestrator instructions (`data/CLAUDE.md` / `data/AGENTS.md`)** for multi-project sessions: infer the working project from conversation flow, recap the *arriving* project's recent history on context switch via `dispatch_history(B, n=3)`, and brief the portfolio (group `recent[]` by project, include `output_preview`) both on explicit asks and unprompted when churn is high. Explicitly framed as taste/sense, not hard rules.

### Changed
- **Watch output — agent line now bold.** The `agent: …` line in each dispatch `start` event in `central-mcp watch <project>` is bold instead of dim, making it obvious at a glance that per-dispatch overrides and fallback chains can pick a different agent than the project's registry default.
- **Instruction files switched to English only.** Dropped the remaining Korean phrasing (`결과는?` / `결과?` recall cues and the conversational examples) from `data/CLAUDE.md` / `data/AGENTS.md`; these files are consumed by every orchestrator regardless of user locale. `README_KO.md` remains as the translated documentation surface.

### Documentation
- README / README_KO: rewrote "Permission modes" to explain `bypass` / `auto` / `restricted` with a vendor-naming map (claude `--dangerously-skip-permissions`, codex `--dangerously-bypass-approvals-and-sandbox`, gemini `--yolo`, droid `--skip-permissions-unsafe`, opencode `--dangerously-skip-permissions`) and the claude-only constraint on `auto` (Team/Enterprise/API + Sonnet/Opus 4.6).
- README / README_KO: added a tight "Why the observation layer is *optional*" block — orchestrator is the primary surface, work should be possible from anywhere (including mobile/remote-access), observation helps only for live monitoring.

### Note for upgrading users
- `data/CLAUDE.md` / `data/AGENTS.md` are copied into `~/.central-mcp/` on first launch only (copy-on-miss). Existing users will not see the new multi-project guidelines until they delete or overwrite their local copies and relaunch.

## [0.5.1] — 2026-04-19

### Changed
- Zellij layouts now pin the `tab-bar` plugin to the **bottom** of every tab instead of the top. Keeps the first visible line of each pane (command banner, prompt) at the terminal's top edge where the eye lands first, and matches the convention most tmux/zellij users already have for status rows.

## [0.5.0] — 2026-04-19

### Added
- **`permission_mode` field on every project** (`"bypass"` | `"auto"` | `"restricted"`). Replaces the previous boolean `bypass` field. `"auto"` is claude-only — emits `--enable-auto-mode --permission-mode auto` and uses the classifier-reviewed flow (requires Team/Enterprise/API plan + Sonnet 4.6 or Opus 4.6). Other agents map `"auto"` to no permission flags; dispatch refuses chains that mix `"auto"` with non-claude agents so intent isn't silently downgraded.
- **`--permission-mode {bypass,auto,restricted}`** on every orchestrator subcommand (`run`, `up`, `tmux`, `zellij`). Default is `bypass` to preserve 0.4.x launch behavior.

### Changed
- **BREAKING** — `dispatch(bypass=...)` → `dispatch(permission_mode=...)` MCP tool parameter.
- **BREAKING** — `update_project(bypass=...)` → `update_project(permission_mode=...)` MCP tool parameter.
- **BREAKING** — `Adapter.exec_argv(..., bypass=bool)` → `exec_argv(..., permission_mode=str)`. External adapter implementations must update their signatures.
- **BREAKING** — registry YAML: `bypass: bool | None` field replaced by `permission_mode: str | None`. Old registries keep their project entries but lose their saved permission preference on first write (default re-applied is `"bypass"`).
- New projects no longer trigger the `needs_bypass_decision` prompt on first dispatch — they default to `permission_mode="bypass"` and save it to the registry immediately.

### Removed
- **BREAKING** — `--bypass` / `--no-bypass` CLI flags across `run`, `up`, `tmux`, `zellij`. Use `--permission-mode` instead.
- **BREAKING** — `needs_bypass_decision` MCP response key. Dispatch no longer requires an explicit decision before the first call.
- `BYPASS_FLAGS` constant and `update_project_bypass` helper — internal API callers should use `PERMISSION_MODE_FLAGS` and `update_project(permission_mode=…)`.

### Rationale
Auto mode (introduced in Claude Code's recent releases) runs a background classifier over every action instead of a blanket permission-skip. It blocks risky categories by default (force-push, prod deploys, `curl | bash`) while letting routine cwd-local work through without prompts. Central-mcp's dispatch path still defaults to `bypass` because auto requires Sonnet/Opus 4.6 and Team/Enterprise/API plans — but projects that meet those requirements can now opt in per-project via `update_project(name, permission_mode="auto")` or per-dispatch via `dispatch(name, prompt, permission_mode="auto")`.

## [0.4.2] — 2026-04-19

### Fixed
- Zellij overflow tabs now actually tile project panes in a 2×2 grid. 0.4.1's changelog declared this behavior, but the implementation (`_tile_panes` + `_indent` helpers wired into `_project_tab_kdl`) was missing from the release commit. 0.4.2 backfills the code so it matches what 0.4.1 promised.

## [0.4.1] — 2026-04-18

### Fixed
- Zellij hub tab now holds `panes_per_window - 1` panes (orchestrator + `panes_per_window - 2` projects), matching the tmux contract. Previously it held `panes_per_window` panes, crowding the hub.
- Zellij overflow tabs tile panes in a 2-column grid instead of a single vertical list, so 4 watch panes fill the screen as a 2×2 grid.

## [0.4.0] — 2026-04-18

### Added
- **Zellij observation backend** — `central-mcp zellij` generates a KDL layout (hub tab `cmcp-1-hub` with orchestrator on the left half + project panes stacked on the right, overflow tabs `cmcp-2`, `cmcp-3`, … for larger registries) and launches or attaches to a zellij session named `central`.
- **`central-mcp up` is now a backend picker** — detects both tmux and zellij on PATH. With only one installed it uses it silently; with both, prompts every launch (no preference saved) and delegates to `cmd_tmux` / `cmd_zellij`. `central-mcp tmux` / `central-mcp zellij` remain as explicit backend entry points.
- **Read-only observation panes** — project watch panes wrap the command with `stty -echo -icanon </dev/null; …; sleep infinity` so keystrokes in a watch pane produce no visible effect, the watch can't read stdin, and the pane doesn't drop to a shell on exit. Applies to both tmux and zellij layouts.
- **Backend-agnostic `central-mcp down`** — tears down whichever backend holds the `central` session (or both).

### Fixed
- Zellij session launch used `--layout` which in zellij 0.43 means "append to existing session"; switched to `--new-session-with-layout` (`-n`) + `--session NAME` so a fresh session is created with the desired name.
- Zellij layout now has a `default_tab_template` with the `tab-bar` plugin so tab names are visible at the top of every tab.
- `cmd_down`'s zellij branch replaced `kill-session` (which returned empty stderr for stale sessions) with `delete-session --force` so both active and EXITED sessions are cleaned up.

### Changed
- README / README_KO document both backends in the observation-layer section and the CLI reference.

## [0.3.2] — 2026-04-18

### Fixed
- `central-mcp install claude` / `install all` is now truly idempotent — probes with `claude mcp get central` first and returns "no change" when already registered, instead of surfacing `claude mcp add`'s "already exists" stderr on every rerun.

### Changed
- Quickstart in both READMEs collapsed to a single command (`central-mcp`) — relies on the 0.3.1 cold-start bootstrap.

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
