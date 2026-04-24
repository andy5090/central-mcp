# Changelog

All notable changes to central-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.10.9] — 2026-04-24

### Fixed
- **Sub-agent polling no longer reports "no dispatch with id"** when the orchestrator dispatches from one central-mcp stdio session and then spawns a sub-agent (e.g. Codex `spawn_agent`) to poll on its behalf. Until now each MCP stdio connection got its own central-mcp process with a private in-memory `_dispatches` dict, so the sub-agent's central-mcp had no record of the dispatch even though the parent's did. The real-world symptom was `check_dispatch("abc12345") → "no dispatch with id 'abc12345'"` from the polling sub-agent even though the parent had just started it. This broke the sub-agent-based "non-blocking wait" pattern Codex users rely on.

### Added
- `central_mcp.dispatches_db` — shared dispatch state at `~/.central-mcp/dispatches.db` (SQLite). One row per dispatch, overwritten on each state transition (`running → complete/error/cancelled/timeout`). Writes are best-effort (swallowed on failure); in-memory state still wins for the originating process (free, no I/O) and the DB serves as the authoritative cross-process fallback. `check_dispatch` and `list_dispatches` now consult it automatically when the record isn't in the caller's in-memory dict.

### Scope
- Intentionally Codex-first: every dispatch created by any agent is mirrored to the DB (the store is agent-agnostic), but the explicit motivation is the Codex `spawn_agent` polling pattern that surfaced this bug. Other agents (Claude Code, Gemini, opencode) already work fine via in-memory state when the same central-mcp handles both the dispatch and the polls; they inherit the new cross-process read-through for free and won't regress. Broader testing across agents is the next milestone.

### Notes for existing installs
- No runtime-doc changes (no need to remove `~/.central-mcp/{CLAUDE,AGENTS}.md`). The DB file at `~/.central-mcp/dispatches.db` is created lazily on first dispatch; delete it any time to reset shared state.

---

## [0.10.8] — 2026-04-24

### Changed
- **Background-poll interval reduced from 30s → 3s** in orchestrator guidance. The 30s figure was a conservative placeholder from v0.2.0; analysis of ~170 real dispatches across all five agents shows a median duration of ~80s and a minimum of ~6s (codex), so 30s polls meant users sometimes waited 30+ seconds past completion before being told. 3s puts the average completion-to-report gap under 1.5s while keeping the total tool-call rate reasonable for the typical 80s dispatch (~25 polls). `check_dispatch` is an in-memory lookup — cheap enough that aggressive polling doesn't matter server-side. Guidance updated in `_MCP_INSTRUCTIONS`, `data/CLAUDE.md`, `data/AGENTS.md`.

### Notes for existing installs
- Runtime doc copies at `~/.central-mcp/{CLAUDE,AGENTS}.md` are written on first launch and not overwritten by upgrades. To pick up the new poll cadence:
  ```bash
  rm ~/.central-mcp/CLAUDE.md ~/.central-mcp/AGENTS.md
  ```
  The shipped `_MCP_INSTRUCTIONS` string reloads automatically on MCP client restart.

---

## [0.10.7] — 2026-04-24

### Added
- **Startup upgrade probe** — `central-mcp run` now probes PyPI at launch (at most once per 24h) and, when a newer release is out, offers to upgrade interactively with a simple Y/n prompt. Declined prompts are remembered for the interval window so users aren't nagged every invocation. Every failure path (network error, non-TTY shell, not-yet-installed from source) is silent — this never blocks startup. Controlled by:
  ```toml
  [user]
  upgrade_check_enabled         = true    # default true; set false to disable
  upgrade_check_interval_hours  = 24      # default 24
  ```
- `upgrade.check_available_silent(timeout)` helper for reuse (short-timeout, exception-swallowing probe that returns `(current, latest)` or `None`).

---

## [0.10.6] — 2026-04-24

### Fixed
- **`token_usage` now advertised in orchestrator instructions.** The tool shipped in 0.10.0 but was missing from the MCP `_MCP_INSTRUCTIONS` string and from `src/central_mcp/data/{CLAUDE,AGENTS}.md`, so orchestrators kept falling back to the legacy "read `timeline.jsonl` / call `orchestration_history()` for token counts" path even though both are wrong now (timeline has no `tokens` field; orchestration_history deliberately dropped it in 0.10.0). Also added explicit "DOES NOT carry token counts — call `token_usage`" to the `orchestration_history` blurb so the wrong path stops being tried.
- **`list_project_sessions` added to the AGENTS.md tool table** (was missing despite shipping since 0.9.x).

### Notes for existing installs
- Runtime doc copies at `~/.central-mcp/CLAUDE.md` / `~/.central-mcp/AGENTS.md` are written on **first launch** and not overwritten by upgrades. To pick up this update, remove those two files before the next orchestrator launch:
  ```bash
  rm ~/.central-mcp/CLAUDE.md ~/.central-mcp/AGENTS.md
  ```
  The shipped `_MCP_INSTRUCTIONS` string (injected at MCP server startup) updates automatically — restart your MCP client to reload it.

---

## [0.10.5] — 2026-04-24

### Added
- **opencode orchestrator-session backfill** — `orch_session.sync_orchestrator("opencode")` now reads opencode's sessions and populates `tokens.db` with `source='orchestrator'` rows alongside the existing Claude Code + Codex support. Hybrid strategy: a 3-column read from opencode's SQLite session table for discovery (stable schema), then `opencode export <id>` CLI for the per-turn token content (public contract). `agents.AGENTS["opencode"].has_session_reader` flipped to True; drift-guard tests confirm the implementation is wired up.

---

## [0.10.4] — 2026-04-24

### Added
- **Orchestrator fallback with quota awareness** — `central-mcp run` now walks a chain instead of hard-launching the saved preference. The chain is: `preferred → config.toml [orchestrator].fallback (optional hint) → remaining installed orchestrator-capable agents`. Any entry whose provider-reported 5h or weekly quota meets/exceeds the configured threshold (default 95% / 90%) is skipped with a one-line notice to stderr, and the next candidate is tried. Configure with:
  ```toml
  [orchestrator]
  fallback_enabled = true           # default true; set false to disable entirely
  # fallback = ["codex", "gemini"]  # optional: explicit order hint
  [orchestrator.quota_threshold]
  five_hour = 95
  seven_day = 90
  ```
- `config.orchestrator_fallback_enabled()`, `config.orchestrator_fallback()`, `config.quota_threshold()` helpers — all respect `config.toml` with sensible defaults.
- 17 tests covering the quota-skip heuristic, chain ordering with user hints, uninstalled/non-orchestratable agent exclusion, and custom thresholds.

---

## [0.10.3] — 2026-04-24

### Added
- **`central_mcp.agents` — capability registry** (single source of truth) with an `AGENTS` dict of `AgentCapabilities` (can_dispatch / can_orchestrate / mcp_installable / has_quota_api / has_session_reader) plus helpers (`get`, `filter_by`, `installed`, `is_installed`). Legacy `ORCHESTRATORS` / `VALID_AGENTS` / `SUPPORTED_CLIENTS` are re-exported from here so pre-existing imports keep working. Consistency tests in `tests/test_agents.py` catch future drift (declared capability with no implementation, or vice versa).

### Fixed
- **opencode now appears in the `central-mcp run` picker** — it was added to dispatch (`VALID_AGENTS`) and MCP install (`SUPPORTED_CLIENTS`) in earlier releases but `ORCHESTRATORS` was never updated alongside, so the interactive picker showed only claude/codex/gemini. The new `agents` registry is the single source of truth, so this kind of drift can't silently happen again.

---

## [0.10.2] — 2026-04-24

### Added
- **Arrow-key interactive picker** — when `central-mcp run` or `central-mcp up` needs to choose between multiple installed coding agents / multiplexers, it now renders an arrow-key navigable list (↑/↓ or k/j, Enter to select, Esc/q to cancel) instead of the legacy numbered input. Non-TTY environments (piped stdin, Windows without termios) transparently fall back to the number-prompt path — same contract, same defaults. Shared `_arrow_select` helper drives both pickers.

---

## [0.10.1] — 2026-04-24

### Fixed
- **`list_projects()` (no args) now scopes to the current workspace.** The default was "all registered projects across every workspace" — which misled orchestrators into replying with the whole portfolio when the user was only working in one workspace. Now `list_projects()` returns projects in `config.toml [user].current_workspace`; pass `workspace="<name>"` for a specific workspace, or `workspace="__all__"` (alias: `"*"`) for the old global listing. This matches the existing `__all__` convention already documented in `data/CLAUDE.md` / `data/AGENTS.md`.

---

## [0.10.0] — 2026-04-24

### Added
- **`central-mcp monitor` — portfolio-wide dashboard** — a new curses subcommand that shows:
  - **AGENT QUOTA** for each coding-agent CLI:
    - `claude` (Pro/Team/Enterprise OAuth): 5-hour and weekly utilization bars with reset ETAs, polled from `api.anthropic.com/api/oauth/usage` using the token in `~/.claude/.credentials.json`. API-key users see "no subscription quota".
    - `codex` (ChatGPT plan): 1-hour and daily `used_percent` bars with reset ETAs, polled from `chatgpt.com/api/codex/usage` using the token in `~/.codex/auth.json`. API-key users see "no subscription quota".
    - `gemini`: auth type only (no quota API is exposed by Gemini).
  - **DISPATCH STATS (today UTC)**: per-project dispatch count, token total, last dispatch time/status, plus a portfolio-wide token sum — aggregated from `~/.central-mcp/timeline.jsonl`. Quota refreshes every 90s in a background thread; stats every 10s.
- **New `central_mcp.quota` package** (`claude.py`, `codex.py`, `gemini.py`) — standalone fetchers that return `{"mode": "api_key"}` / `{"mode": "pro"/"chatgpt", "raw": …}` or `None` (CLI not installed). Safe to call from tests or other UIs.
- **Token counts in `timeline.jsonl`** — `log_timeline()` now records the parsed `tokens` dict (when the agent reported one), so the monitor and `orchestration_history` can aggregate portfolio-wide token usage without re-parsing stdout.
- **`per_project.tokens_total` in `orchestration_history`** — daily token totals per project are now exposed in the MCP response alongside `dispatched` / `succeeded` / `failed` / `cancelled`.

### Added
- **Timeline rotation infrastructure** — `log_timeline()` now opportunistically rotates `~/.central-mcp/timeline.jsonl` into `~/.central-mcp/archive/timeline-<utc-microsecond>.jsonl` once the live file exceeds 5 MB (or 10,000 lines). Each rotated file is accompanied by a compact `*-summary.json` holding per-project dispatched/succeeded/failed/cancelled counts, per-agent event counts, record count, and the `{from, to}` ts range — so long-past history stays queryable without raw records bloating context. Thresholds are module-level constants and dormant in practice at current install sizes; the structure is in place for when timelines grow.
- **`orchestration_history(include_archives=True)`** — new parameter attaches an `archived_summaries` array (summaries only, never raw records) so orchestrators can ask for "the full shape of history" without blowing past context.
- **Orchestrator-session token backfill** (`central_mcp.orch_session`) — `dispatch()` now sniffs the active orchestrator's own session file on every call, parses per-turn token usage (Claude Code: `~/.claude/projects/<slug>/*.jsonl`, Codex: `~/.codex/sessions/**/rollout-*.jsonl`), and inserts each turn into `tokens.db` with `source='orchestrator'`. UNIQUE(source, session_id, request_id) makes re-syncs idempotent, so a full-file scan on every dispatch is safe. Gemini has no on-disk session store and is a no-op; opencode (SQLite-backed) lands in a follow-up. `config.orchestrator_default()` helper added.
- **Adapter-driven structured-output parsing (replaces stdout regex)** — each adapter's `exec_argv` now appends the agent's JSON-output flag (`claude --output-format json`, `codex --json`, `gemini -o json`, `droid -o json`, `opencode --format json`) and a new `parse_output(stdout)` method normalizes that JSON/JSONL into `(display_text, {input, output, total})`. The previous regex path (`_TOKEN_PATTERNS` / `_extract_token_usage`) matched 0% in practice because the underlying CLIs don't emit tokens in plain stdout; this path gets us deterministic, 100% coverage on all five supported agents. Gemini aggregates across multiple models per request (router + main). `dispatch` results now carry the extracted display text as `output` and the parsed counts as `tokens`.
- **`token_usage` MCP tool** — portfolio-wide token aggregation separated from event/dispatch history so each surface can evolve independently (paves the way for a live token pane). Parameters: `period` (`today`/`week`/`month`/`all`), `project`, `workspace`, `group_by` (`project`/`agent`/`source`). Response includes the resolved window, grouped breakdown, and aggregate total. All reads are windowed by the user's configured timezone.
- **`tokens.db` SQLite aggregation store** (`~/.central-mcp/tokens.db`) — a flat `usage` table holds one row per observed token-reporting event, keyed by `(source, session_id, request_id)` so re-syncs are idempotent. `source` is either `dispatch` (subprocess run) or `orchestrator` (derived from session files — wiring lands in a follow-up). `monitor` and `orchestration_history` now read token totals (today + last 7d) via `SUM(...) GROUP BY project` from this table instead of scanning `timeline.jsonl`.
- **monitor dashboard: today + last-7d columns** — the DISPATCH STATS section now shows two token columns (`today tok` / `7d tok`) plus a header summary (`today: N  │  last 7d: M`). The user's `config.toml [user].timezone` defines the "today" boundary.
- **`orchestration_history` no longer carries token fields** — callers who want token totals should call the dedicated `token_usage` tool. Event history and token accounting are now distinct surfaces. (The short-lived `tokens_today`/`tokens_week` fields introduced earlier in this release are removed before first publication.)

### Changed
- **`current_workspace` moved from `registry.yaml` → `config.toml`** — it's a per-user UI state, not a shared project record, so it lives alongside the other user preferences now. `ensure_initialized()` performs a one-shot migration on startup: lifts the value out of `registry.yaml` into `[user].current_workspace` and deletes the legacy key. No user action needed.
- **`config.toml` auto-seeded with system timezone** — `[user].timezone` is now injected on install/upgrade (idempotent, runs at every startup) so the file reflects a concrete IANA name (e.g. `Asia/Seoul`) the user can inspect/edit rather than an invisible fallback. Falls back to `/etc/localtime` → `UTC` on misconfigured hosts.

### Added
- **`central_mcp.config` module** — centralized read/write for `~/.central-mcp/config.toml` with `user_timezone()` / `current_workspace()` / `ensure_initialized()` helpers. Previous `[orchestrator].default` handling carried over; new `[user]` section adds `timezone` + `current_workspace`.

### Fixed
- **`log_timeline()` concurrency** — writes to `~/.central-mcp/timeline.jsonl` now go through a `threading.Lock` + `fcntl.flock` (POSIX) so ts-generation and file append are atomic as a pair. Previously, the MCP handler thread and `_run_bg` daemon threads could race between `datetime.now()` and `f.write()`, letting the file's line order diverge from ts order — which would have broken monitor's reverse-scan early-break under concurrent writes. Windows native (no `fcntl`) falls back to `threading.Lock` only.

---

## [0.9.5] — 2026-04-23

### Added
- **`get_user_preferences` MCP tool** — returns the current content of `~/.central-mcp/user.md` so orchestrators can read existing preferences before merging in new ones.
- **`update_user_preferences(section, content)` MCP tool** — writes a named section of `user.md` atomically. Sections: `"Reporting style"`, `"Routing hints"`, `"Process management rules"`, `"Other preferences"`. Other sections are left untouched; the file is created if missing. Response includes `updated_preferences` (full updated content) so the orchestrator applies changes immediately without session restart.
- **user.md injected into MCP system prompt** — `user.md` content is now included in the MCP server's `instructions` field at startup, so it lives in the system prompt and is never lost to context compression. Previously, orchestrators had to re-read the file manually.
- **Orchestrators instructed to auto-persist preferences** — `AGENTS.md` / `CLAUDE.md` now tell the orchestrator: when the user expresses a persistent preference (language, reporting style, routing hint, process rule), call `get_user_preferences` + `update_user_preferences` immediately and confirm to the user that it was saved.

### Changed
- README / `pyproject.toml`: description updated from "Orchestrator-agnostic" to "Coding agent-agnostic" — more accurate since the hub works regardless of which coding agent CLI is used on either side (orchestrator or dispatch target).

---

## [0.9.4] — 2026-04-23

### Added
- **User preference overlay** — `~/.central-mcp/user.md` is scaffolded on first `cmcp` launch. Edit it to set persistent reporting style, routing hints, and process-management rules; orchestrators read it at session start and apply it on top of shared defaults. The file is never overwritten by upgrades.
- **Watch mode visual improvements** — `central-mcp watch` output is now context-aware:
  - Elapsed-time prefix (`+  42s`) on every output line while a dispatch is active.
  - Code blocks (` ``` ` / `~~~` fences) rendered in magenta to separate prose from code.
  - Spinner, progress-bar, and blank lines dimmed to reduce visual noise.
  - Fallback `attempt_start` transitions rendered in yellow with a `↻` arrow instead of plain dim text.
- **Token usage monitoring** — dispatch result, `dispatch_history`, and the per-project watch `complete` footer now include a `tokens` field (`{input, output, total}`) when the agent reports token counts in its stdout. Regex patterns cover Claude Code, Codex, and Gemini output formats; returns `null` when not detected.

### Notes for existing installs
Because `AGENTS.md` and `CLAUDE.md` now reference `user.md`, existing installs will auto-update those files on the next `cmcp` launch (0.9.3 behaviour). `user.md` itself is only created if absent — your edits are preserved.

---

## [0.9.3] — 2026-04-23

### Changed
- **Runtime files auto-update on upgrade** — `AGENTS.md` and `CLAUDE.md` in `~/.central-mcp/` are now overwritten on every `cmcp` launch when the packaged content differs from what is on disk. Previously these files were copied only once (if missing), so upgrades never reflected updated orchestrator instructions without manually deleting the files. No manual deletion needed going forward.

---

## [0.9.2] — 2026-04-23

### Changed
- **Orchestrator auto-reporting** — `AGENTS.md` and `CLAUDE.md` now instruct orchestrators to always proactively report dispatch results without waiting for the user to ask "status?":
  - Claude Code: `Agent(run_in_background=True)` to poll `check_dispatch` every 30 s (required, not optional).
  - Codex: `spawn_agent` for background polling — Codex's multi-agent API supports non-blocking sub-agents equivalent to Claude Code's background agents.
  - Gemini / other: synchronous polling loop until complete, then report.
- **`_MCP_INSTRUCTIONS`** updated to document all three orchestrator polling paths inline.
- **Roadmap restructured** — phases consolidated around user value: Phase 4 UX & personalization (user overlays + watch improvements + token monitoring), Phase 5 Distribution & docs, Phase 6 Daemon + push notifications, Phase 7 Agent harness. Interactive approval worker mode removed (non-goal).

### Notes for existing installs
Runtime orchestrator files are copied once on first launch. To pick up the updated polling instructions:
```bash
rm ~/.central-mcp/AGENTS.md ~/.central-mcp/CLAUDE.md
# restart cmcp — files are re-copied automatically
```

---

## [0.9.1] — 2026-04-22

### Added
- **Workspace-aware MCP tools** — all four primary tools now understand workspaces:
  - `list_projects(workspace=...)` — filter results to a named workspace.
  - `dispatch("@workspace", prompt)` — fan-out: dispatches the prompt to every project in the workspace simultaneously; returns `{workspace, dispatches: [{project, dispatch_id, …}, …]}`.
  - `orchestration_history(workspace=...)` — filter in-flight, recent milestones, and per-project stats to a single workspace.
  - `add_project(…, workspace=...)` — register a project and add it to a workspace in one call.

---

## [0.9.0] — 2026-04-22

### Added
- **Workspaces** — group projects into named sets; switch between them without editing `registry.yaml` directly.
  - `cmcp workspace list / current / new / use / add / remove` CLI subcommand tree.
  - `current_workspace` stored in `registry.yaml` (no separate config file); auto-migrated on first load.
  - Projects not assigned to any named workspace fall back to the built-in `default` workspace (orphan logic).
  - Registry functions: `load_workspaces`, `current_workspace`, `set_current_workspace`, `add_workspace`, `add_to_workspace`, `remove_from_workspace`, `projects_in_workspace`.
- **Workspace-aware observation sessions** — `cmcp tmux` / `cmcp zellij` now create sessions named `cmcp-<workspace>` (e.g. `cmcp-default`, `cmcp-work`) instead of the generic `central`.
  - `--workspace NAME` targets a specific workspace; `--all` creates sessions for every workspace simultaneously.
  - `cmcp tmux switch NAME` / `cmcp zellij switch NAME` jump to `cmcp-<NAME>`, creating it if missing.
  - `cmcp down` tears down all `cmcp-*` sessions (including the legacy `central` name for backward compat).
- **Multi-workspace cmux recipe** added to shipped `src/central_mcp/data/{CLAUDE,AGENTS}.md` — in `--all` mode, the orchestrator creates one `cmcp-<workspace>-watch-<n>` workspace per group chunk.

### Changed
- Session naming: `cmcp-<workspace>` replaces the hardcoded `central` name. The old name is kept as a backward-compat alias and cleaned up by `cmcp down`.
- `kill_all()` now accepts an optional `session_name` argument — `None` kills all `cmcp-*` sessions; a specific name kills just that session.
- README / README_KO updated with Workspaces section, updated CLI reference, and session naming notes.

### Upgrade note
- Because the shipped runtime orchestrator instructions changed, existing installs may need `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the updated bundle.

---

## [0.8.19] — 2026-04-22

### Added
- **Same-project concurrent dispatch conflict mitigation.** When a `dispatch()` call arrives for a project that already has one or more running dispatches, the new dispatch receives a concise conflict-awareness preface prepended to its prompt listing each sibling's `dispatch_id`, elapsed time, and prompt preview. The agent can then avoid editing the same files. The `dispatch()` return value gains an optional `conflict_warning` field (`sibling_count`, `dispatch_ids`) so orchestrators can surface the situation without parsing the prompt.
- `_running_siblings()` / `_build_conflict_preface()` helpers in `server.py` (internal).
- 5 new tests in `tests/test_dispatch.py` covering: solo dispatch (no warning), sibling warning present, preface reaches the subprocess, preface stays out of `dispatch_history`, and cross-project isolation.

### Changed
- `dispatch_history` and the event log always store the clean, pre-conflict-preface prompt so history stays readable even when the agent received an augmented version.

---

## [0.8.18] — 2026-04-22

### Added
- **`list_project_sessions` now returns a bounded `preview` field** alongside `id` / `title` / timestamps so users can recognize a thread without manually resuming each candidate session. JSONL-backed adapters (claude, codex, droid) pull a short best-effort snippet from early session content; CLI-backed adapters (gemini, opencode) fall back to their title-like output when deeper inspection is not cheaply available.

### Fixed
- **cmux observation-mode grids now snap to halving-safe dimensions before the orchestrator builds them.** The shipped `src/central_mcp/data/{CLAUDE,AGENTS}.md` recipe previously allowed 3-way row/column counts from raw terminal budgets (for example `300×50 -> 3×4`), but cmux only exposes repeated 50/50 splits, so those layouts could never become a clean balanced grid. The recipe now snaps each axis down to a power of two first, yielding clean shapes like `2×2`, `2×4`, and `8×1`.
- **One-shot `dispatch(language=...)` overrides now use the same sanitization as saved project language pins.** This keeps the prompt-preface mechanism backward-compatible while rejecting control characters/newlines instead of pasting them straight into the dispatch prompt.

### Changed
- README / README_KO / shipped orchestrator guidance now document both the new session `preview` field and the per-project language preference flow more clearly, including the fact that language defaults remain unchanged unless explicitly pinned or overridden.

### Upgrade note
- Because the shipped runtime router instructions changed again, existing installs may need `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the new bundle.

## [0.8.17] — 2026-04-21

### Fixed
- **cmux observation-mode misses were NOT a timing race — they're an input-discard during shell init.** 0.8.16 evidence (real pane contents): text like `ntral-mcp watch andineering` appearing on the same line as `Last login:` — multiple characters silently eaten, not a single-byte jitter. zsh + heavy oh-my-zsh themes flush pending stdin at an unpredictable moment in their rc processing, so any fixed `sleep` is always guessing.
- **Recipe swapped from fixed sleep to per-surface readiness polling.** The shipped `src/central_mcp/data/{CLAUDE,AGENTS}.md` now tells the orchestrator to poll `cmux tree --json` per surface, waiting for either `tty` to become non-null or `title` to become non-empty (shell attached + first prompt rendered), then send. Works on slow shell setups that `sleep 2.0` didn't cover.
- Leading `\n` in the send is retained as a cheap defense against any residual single-byte race; the primary guarantee is now the readiness poll.
- Retry-just-the-misses guidance kept in the recipe since polling isn't 100% (genuinely broken surfaces can still fail).

### Upgrade note
- Same copy-on-miss caveat: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch.

## [0.8.16] — 2026-04-21

### Fixed
- **cmux observation-mode seeding still missed some panes even after the 0.8.15 `sleep 0.5`.** 3-of-8 panes came out empty in a recent test. The 0.5s wasn't always enough, and even when the shell was ready the single-byte-drop race could eat the leading `c` of `central-mcp`. Two-line strengthening in the shipped `src/central_mcp/data/{CLAUDE,AGENTS}.md` recipe:
  - **Default sleep raised to `1.0s`** after grid construction (bump to `2.0s` if still flaky — slow machines / cold cmux startup).
  - **Every send now leads with `\n`** so if any byte is dropped the casualty is a harmless newline, not the command's first character. Concrete: `cmux send ... "\ncentral-mcp watch <name>"` followed by `cmux send-key ... enter`. 
- Recipe also now explicitly permits the orchestrator to retry just the failed surfaces if a pane still lands empty — safer than requiring a full teardown+rebuild for partial misses.

### Upgrade note
- Same copy-on-miss caveat: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the revised recipe.

## [0.8.15] — 2026-04-21

### Fixed
- **cmux observation-mode race between `new-split` and `send`.** Some watch panes came out empty after the bootstrap — the split succeeded but `central-mcp watch <project>` never actually ran, leaving a bare prompt. Cause: the pane's shell hadn't finished spawning before the orchestrator's `cmux send` arrived, so the opening keystrokes got dropped. Recipe in `src/central_mcp/data/{CLAUDE,AGENTS}.md` now tells the orchestrator to insert a short delay (`sleep 0.5`, tunable up to 1s) between finishing the grid construction and sending watch commands. Cheap across 8+ projects since the sleep happens once after all splits, not per-pane.

### Upgrade note
- Same copy-on-miss caveat: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the revised recipe.

## [0.8.14] — 2026-04-21

### Changed
- **cmux observation-mode trigger phrasing made more user-friendly** in the shipped orchestrator guidelines (`src/central_mcp/data/{CLAUDE,AGENTS}.md`). The primary example the orchestrator keys off of used to be "관찰 pane 구성해줘" / "set up watch panes" — implementation-centric wording. The new primary examples are "관찰 모드 켜줘" / "turn on observation mode" (feature-centric, matches how users naturally think about it); older phrasings still work since the LLM generalizes from the listed examples. READMEs updated to match.

### Upgrade note
- Same copy-on-miss caveat as prior 0.8.x runtime-file releases: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the new phrasings. Old phrasings keep working regardless.

## [0.8.13] — 2026-04-21

### Changed
- **README / README_KO: new "First session — natural-language examples" section** right after Quickstart. Replaces the 4-bullet snippet in Quickstart with a grouped catalog (setup / send work / check progress / recover+switch threads / shape fleet), all phrased as things the user says to the orchestrator. Explicit note that `dispatch(...)` / `add_project(...)` etc. are MCP-layer function names shown for reference — users never type those. Also surfaces the "start with observation, drop it later" onboarding tip near the top with a link to the full explanation in the Observation layer section.
- **Performance tip reworded.** Claude Opus 4.7 is fast enough that routing turns aren't latency-bound anymore (~2-3s/turn), so the old "Sonnet for speed" framing was misleading. Rewrote as a **cost** tip: the orchestrator takes many short turns, and those add up in tokens — downgrading to Sonnet (or Haiku) is primarily a billing optimization, not a speed one. Framed both README and README_KO the same way.

## [0.8.12] — 2026-04-21

### Changed
- **cmux grid layout now aspect-matches the window.** The earlier formula — `rows = H // 15`, `cols = W // 70` — picked max rows and max cols independently, so a landscape window like `200×50` produced `max_cols=2, max_rows=3` → a **3×2** grid (3 rows of 2 panes) inside a wide window. Visually wrong: a landscape container should host a landscape grid. 0.8.12 adds an aspect clamp on top of the floor:
  - Landscape window (`W >= H`): `rows_per_ws = min(max_rows, max_cols)`, `cols_per_row = max_cols`. Grids never go taller than they are wide.
  - Portrait window (`W < H`): `cols_per_row = min(max_cols, max_rows)`, `rows_per_ws = max_rows`. Grids never go wider than they are tall.
- Result at `200×50`: `2×2` (was `3×2`). At `300×50`: `3×4`. At `80×200`: `1×13`. Matches the window's long axis.

### Upgrade note
- Same copy-on-miss caveat: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the clamp.

## [0.8.11] — 2026-04-21

### Fixed
- **`cmcp upgrade` no longer lies about the target version.** The version check used PyPI's legacy `/pypi/<name>/json` endpoint (`info.version` field), which is aggressively CDN-cached and typically trails reality by several minutes. Meanwhile `uv tool install --refresh` hits the simple index, which updates within seconds of upload. The disagreement produced confusing output — e.g., "0.8.8 → 0.8.9 available" followed by the actual install landing on 0.8.10. 0.8.11 swaps the check to the simple index (PEP 691 JSON variant at `/simple/<name>/`), parses file-level version stamps, and returns the max — matches the freshness the installer uses.

## [0.8.10] — 2026-04-21

### Changed
- **`cmcp` now exports `CMCP_OBS_W` / `CMCP_OBS_H` env vars on orchestrator launch.** `cmcp` itself runs in a real TTY (it's the process the user types in a cmux pane), so `shutil.get_terminal_size()` reports the actual pane dimensions there. Those values are stashed in env before `os.execvp` to the agent CLI, so the orchestrator inherits them and its Bash tool can read the pre-captured size without needing a PTY of its own. This replaces the 0.8.9 "ask the user" step — the orchestrator now reads `${CMCP_OBS_W:-200}` / `${CMCP_OBS_H:-50}` directly, no conversation needed. Defaults to 200×50 only when `cmcp` itself was launched outside a TTY (rare).

### Upgrade note
- Same copy-on-miss caveat: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the env-var-based recipe. Re-running `cmcp` after the upgrade also re-seeds the env vars at startup.

## [0.8.9] — 2026-04-21

### Fixed
- **Orchestrator no longer trusts `tput cols` / `tput lines` from its Bash tool** during cmux bootstrap. 0.8.8 testing revealed that Claude Code (and likely every agent CLI whose Bash tool pipes stdout instead of allocating a PTY) falls back to the terminfo default of 80×24 regardless of the real pane size — so even in a 300×80 cmux window the orchestrator would see 80×24 and spawn one observation workspace per project. cmux's own CLI exposes no pane geometry either (checked `tree --json`, `identify`, `list-pane-surfaces`; no size fields). Fix: the recipe now explicitly asks the user for the cmux window size as a one-line prompt (suggesting `stty size` in a real pane shell as a reference), defaulting to 200×50 when the user skips.

### Upgrade note
- Same copy-on-miss caveat: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the new "ask the user" step.

## [0.8.8] — 2026-04-21

### Changed
- **cmux pane readability floor aligned with tmux / zellij** — 70 cols × 15 lines per pane (previously 80 × 20). The prior values treated cmux more conservatively than the other backends for no good reason; 0.8.7 testing at 80×24 showed `cmcp-watch-<n>` being spawned one-per-project, which is correct given the old floor but surprising since tmux / zellij *also* collapse to one-pane-per-window at 80×24. Matching `_MIN_PANE_COLS=70` / `_MIN_PANE_ROWS=15` from `src/central_mcp/grid.py` restores parity: the only way to pack more panes per workspace is to enlarge the cmux window, same as tmux / zellij's story.
- **Repo-root `/CLAUDE.md` + `/AGENTS.md` split from runtime copies.** They were previously symlinks into `src/central_mcp/data/` — writing to root silently overwrote the shipped runtime files (observed in this release cycle). Root now holds a **dev-mode** guide (repo layout, testing, release flow, key invariants) aimed at contributors; `src/central_mcp/data/{CLAUDE,AGENTS}.md` stays as the shipped orchestrator runtime guidelines. The dev-mode guide explicitly notes the symlink history as a footgun to avoid.

### Upgrade note
- Same copy-on-miss caveat as prior 0.8.x releases: `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the new floor values.

## [0.8.7] — 2026-04-21

### Fixed
- **PyPI project page logo now renders.** The `<img src="docs/logo.png">` in both README.md and README_KO.md was a repo-relative path — fine on GitHub, broken on PyPI because PyPI doesn't resolve relatives against the source repo. Swapped for the absolute `https://raw.githubusercontent.com/andy5090/central-mcp/main/docs/logo.png` URL so the image renders on both GitHub and PyPI.

## [0.8.6] — 2026-04-21

### Changed
- **cmux bootstrap recipe simplified: always dedicated observation workspaces.** Empirical testing (including wide screens) showed that the orchestrator in practice never executes the wide-branch same-workspace split — it consistently opens dedicated workspaces for watch panes regardless of `W`. The 0.8.3 wide/narrow branching was accurate in theory but unused; 0.8.6 drops it. Observation now *always* goes into separate `cmcp-watch-<n>` workspaces and the orchestrator's workspace is renamed to `cmcp-hub` (mirroring tmux / zellij's `cmcp-1-hub`). Terminal size still gates *how many* watch workspaces and *how densely* to pack each (`rows_per_ws × cols_per_row` respecting the 80 × 20 readability floor), just not whether the orchestrator shares space with them (it never does).
- **Workspace naming aligned with tmux / zellij window convention** — `cmcp-hub` for the orchestrator's workspace (renamed via `cmux rename-workspace`), `cmcp-watch-1`, `cmcp-watch-2`, … for observation workspaces. README / README_KO reference the same names.
- The old `central-mcp watch` / `central-mcp watch 2` workspace names are retired; if you had observation workspaces from 0.8.3–0.8.5 still open, close them manually from cmux's sidebar before running the bootstrap again.

### Upgrade note
- Same copy-on-miss caveat as earlier 0.8.x releases: `rm ~/.central-mcp/AGENTS.md ~/.central-mcp/CLAUDE.md` before the next orchestrator launch to regenerate from the updated bundle.

## [0.8.5] — 2026-04-21

### Added
- **README / README_KO "Suggested onboarding" subsection**, between "Why it's optional" and "Backends". Frames the observation layer as a trust-building phase for first-time users — run `central-mcp tmux` / `zellij` / cmux at the start to watch how the orchestrator picks projects and how dispatches actually progress, then graduate to orchestrator-only once the pipeline is internalized. Explicitly keeps the observation layer "one command away" so dropping it is a default change, not a hard abandonment.

## [0.8.4] — 2026-04-21

### Changed
- **README / README_KO "Running inside cmux" blurb updated** to match the 0.8.3 AGENTS.md rewrite: references the correct cmux verbs (`cmux new-split`, `cmux send`, `cmux send-key` — not the non-existent `send-text`) and explains that the layout mirrors tmux / zellij behavior (same-workspace orchestrator column for wide windows, dedicated `central-mcp watch` workspaces for narrow/overflow). Same version would've left PyPI's project page showing the stale 0.8.1-era wording; this bump re-publishes the corrected README.

## [0.8.3] — 2026-04-21

### Changed
- **cmux bootstrap guideline unified with a terminal-size-aware decision tree.** The 0.8.2 "Running inside cmux" section had two competing procedures (a flat per-project split chain up top, plus a "Recommended recipe" in the Layout note) that the orchestrator could accidentally follow in sequence — one would undo the other. 0.8.3 collapses them into one flow keyed off `tput cols` / `tput lines` read from the orchestrator pane *before* any splits (at that moment the pane still spans the workspace, so `tput` reports workspace totals). Branches:
  - **Wide (`W ≥ 160`)** — orchestrator column in the same workspace + project grid on the right half. Direct parallel to tmux / zellij's `main-vertical` layout.
  - **Narrow (`W < 160`)** — dedicated `cmux new-workspace --name "central-mcp watch"` for the observation layer; no orchestrator column.
  - **Overflow** — extra `central-mcp watch N` workspaces when `N_projects > ws_capacity` (match tmux / zellij's `cmcp-2`, `cmcp-3` overflow window behavior).
  Grid construction now explicitly instructs: first `rows - 1` `new-split down`, then **sequential-within-row / parallel-across-rows** balanced halving. Backed by `cmux tree --json` for surface ↔ project mapping.
- Removed the false claim that `cmux new-workspace` returns a `CMUX_WORKSPACE_ID` (UUID-shaped). It actually returns a `workspace:<n>` ref — use the ref directly where the flag expects a `<id|ref>`.
- Dropped the duplicate "Outside this workflow, the no-Bash rule still applies" line from CLAUDE.md (a stray left over from the 0.8.2 edit).

### Upgrade note
- Same copy-on-miss caveat as 0.8.2: `rm ~/.central-mcp/AGENTS.md ~/.central-mcp/CLAUDE.md` before the next orchestrator launch to regenerate from the updated bundle.

## [0.8.2] — 2026-04-21

### Fixed
- **cmux CLI syntax in `src/central_mcp/data/AGENTS.md` + `CLAUDE.md` corrected.** The 0.8.1 "Running inside cmux" section gave the orchestrator flags that don't match the shipped cmux (0.63.2+) CLI — running them failed immediately and the observation layer never came up. Three concrete fixes:
  - `cmux new-split` takes direction as a positional arg (`cmux new-split right --workspace X`), not `--direction right`.
  - `new-split` stdout already carries the surface id on its `OK <surface-ref> <workspace-ref>` line — no follow-up `list-pane-surfaces` call is needed.
  - `cmux send-text` doesn't exist; the correct verbs are `cmux send ... "<text>"` followed by `cmux send-key ... enter` to submit.
- Added a **layout note**: `new-split right` halves the currently-focused surface each time, so successive splits produce exponentially narrow tail panes. For 4+ projects, open a dedicated workspace (`cmux new-workspace --name "central-mcp watch"`) and build a balanced grid (e.g., `new-split down` then `new-split right` per row) instead of a flat chain.

### Upgrade note
- `~/.central-mcp/AGENTS.md` + `CLAUDE.md` are copied in on first launch only (copy-on-miss). Existing installs keep their old file unless you `rm ~/.central-mcp/AGENTS.md ~/.central-mcp/CLAUDE.md` before the next orchestrator launch, which will regenerate them from the updated bundle.

## [0.8.1] — 2026-04-21

### Removed
- **BREAKING — `central-mcp cmux` subcommand removed.** 0.8.0's bootstrap (spawn a cmux workspace, inject a 1k+ char seed prompt via `new-workspace --command`) proved fragile in practice: cmux 0.63.2 silently truncates long `--command` payloads, and the agent launch step often didn't complete even when the command arrived intact. The replacement is lighter: run `cmcp` yourself from inside a cmux pane, and ask the orchestrator to set up the observation panes. No CLI surface, no subprocess keystroke injection — the orchestrator uses its Bash tool to call `cmux new-split` / `cmux send-text` per project.
- `Adapter.interactive_argv()` was only used by the old `cmd_cmux` bootstrap; removed too.
- `src/central_mcp/cmux.py` module, `tests/test_cmux.py`, `docs/architecture/cmux-layout-schema.md` — all tied to the old bootstrap, all gone.

### Changed
- **`src/central_mcp/data/AGENTS.md` + `CLAUDE.md` gain a "Running inside cmux" section** describing exactly which CLI commands the orchestrator should issue when `CMUX_WORKSPACE_ID` is set and the user asks for observation panes. This is the only place in the orchestrator guidelines where Bash usage is allowed.
- README / README_KO "Running inside cmux" section rewritten to match the new flow: launch cmux.app → `cmcp` in a pane → ask the orchestrator to set panes up.

### Notes
- The declarative-layout draft (whose wire schema lived in `docs/architecture/cmux-layout-schema.md`) is still a path we could take once cmux ships `--layout` on `new-workspace` in a released build. For now the agent-driven flow is more reliable and the docs / code are aligned on it.

## [0.8.0] — 2026-04-21

### Added
- **`central-mcp cmux` — macOS-only observation backend (agent-driven bootstrap).** Opens a workspace titled `central` in cmux (manaflow-ai/cmux), an AppKit / Ghostty-based GUI terminal, hosting a single orchestrator pane. On first user turn, the orchestrator receives a seed prompt that enumerates the registered projects and tells it to call `cmux new-split` / `cmux send-text` to create one `central-mcp watch <project>` pane per project — no user trigger required, because cmux injects `CMUX_WORKSPACE_ID` into the agent's env so the CLI calls target the right workspace automatically.
- **`Adapter.interactive_argv(seed_prompt, permission_mode)` on the adapter base.** Builds argv for an interactive session whose first user turn is the seed prompt. Implemented on claude (positional arg), codex (positional arg), gemini (`-i`). opencode / droid return `None`; `cmd_cmux` refuses those agents with a clear error pointing users at tmux / zellij.
- **Backend detection gates cmux to darwin.** `_detect_multiplexers()` includes cmux only when `platform.system() == "Darwin"`, so Linux / Windows users never see it offered by `central-mcp up`. `cmd_cmux` additionally checks the CLI is on PATH and that the socket at `~/.cmux/cmux.sock` answers a ping before attempting to open a workspace.
- **`cmcp down` closes cmux workspaces too.** The teardown routine resolves the workspace by title → `ref` → `id` via `list-workspaces` and calls `close-workspace --workspace <handle>`. Missing binary / non-darwin hosts skip silently.

### Notes
- **cmux 0.63.2 has no declarative `--layout` flag on `new-workspace`**, only `--name/--description/--cwd/--command`. An earlier draft of this backend assembled a `{pane, split, children}` JSON tree from the cmux source (which already wires `--layout` up) — that code was dead against every shipped release. The agent-driven bootstrap replaces it: central-mcp owns one `new-workspace` call, the orchestrator owns the layout.
- **`--permission-mode restricted` halts the bootstrap** on the first `cmux new-split` approval prompt, leaving the layout incomplete. Use `bypass` (default) or `auto` for unattended setup; a runtime warning is printed when `restricted` is selected.

## [0.7.0] — 2026-04-21

### Added
- **`reorder_projects` MCP tool** — rewrite the registry's `projects[]` order without editing YAML. Lenient by default: names in the `order` list move to the front of the registry in the given sequence; any project not mentioned keeps its original relative position after the reordered prefix, so a partial reorder never requires enumerating every project. `strict=True` enforces a full re-listing. Validates unknown names, duplicates, and in strict mode any missing names; on error the registry is untouched.
- **`central-mcp reorder NAME [NAME ...]` CLI command** — shell-side equivalent of the MCP tool, with `--strict` for the exact-list flavor. After reordering, prints the new registry layout to stdout and a `(rerun cmcp tmux/zellij to rebuild the observation session)` hint to stderr.
- **Orchestrator guideline** in `data/CLAUDE.md` / `data/AGENTS.md` pointing users at `reorder_projects` when the user asks to rearrange the fleet, plus an explicit note that panes in an already-running observation session don't live-swap — the next `cmcp tmux` / `cmcp zellij` picks up the new order (auto-teardown since 0.6.8 makes this a single command).

### Internal
- `central_mcp.registry.reorder(order, *, strict=False)` — the shared primitive. Returns the reordered `Project` list; raises `ValueError` for unknown names / duplicates / (in strict mode) missing names.
- 5 new registry tests (full order, lenient partial, strict coverage error, unknown-name error, duplicate-name error) + 3 MCP-tool tests.

### Notes
- Live pane swap inside a running tmux/zellij session isn't attempted — tmux's `swap-pane` would work for some cases but fighting hub/overflow chunking makes it fragile, and zellij's KDL is static so its running layout can't be reshuffled at all. The 0.6.8 auto-teardown makes "rerun the multiplexer command" a one-step flow, which was judged a better tradeoff than a fragile partial live swap.

## [0.6.9] — 2026-04-21

### Changed
- **Zellij layout restores the stock top-tab / bottom-status chrome.** Earlier releases stripped the `status-bar` plugin entirely while moving `tab-bar` to the bottom; the minimalist look cost new users discoverability of zellij's built-in keybindings (Ctrl-p pane mode, Ctrl-t tab mode, etc). 0.6.9 emits the zellij-native `default_tab_template` — `tab-bar` on row 0, `status-bar` spanning the bottom two rows — so sessions created via `cmcp zellij` now look and feel like a zellij session a user would start on their own.

## [0.6.8] — 2026-04-21

### Changed
- **Observation sessions now rebuild on every `cmcp tmux` / `cmcp zellij`.** Prior behavior: if the `central` session already existed, the commands attached to it verbatim (plus a 0.6.1 stale-version guard that refused to attach and pointed at `--force-recreate`). New behavior: always tear down + recreate + attach, so the layout is freshly built at the current terminal's size and always carries the newly-installed binary. No configuration, no flag — it's the default and only path.
- **BREAKING** — `--force-recreate` removed from `cmcp up` / `cmcp tmux` / `cmcp zellij`. Every invocation is now a "force-recreate" by default, so the explicit flag is redundant. Scripts passing `--force-recreate` will fail with "unrecognized argument" — remove the flag; the behavior is preserved automatically.

### Added
- **Narrow-terminal layout**. On terminals where `cols < 2 × min_pane_cols` (i.e. where even two panes side-by-side would go below the readability floor) the layout now falls back to a flat vertical stack: orchestrator on row 0 full-width, project panes stacked one per row below. Previously narrow terminals capped at `n=1` and left the user with a single full-screen pane even when vertical space was plentiful. The `pick_rows` heuristic returns `r=n` in this regime, and `pick_panes_per_window` scales with `rows // min_pane_rows` so a 60×120 SSH-from-phone session lands on 8 stacked panes (each 60×15) instead of 1.

### Removed
- `central_mcp.session_info.staleness_warning` and the three tests that covered it. With auto-rebuild on every invocation the staleness guard never fires — the module survives as a lightweight version stamp for debugging / introspection but no longer gates attach.

### Results on tall / narrow terminals
| Terminal            | 0.6.7 | 0.6.8 (narrow-mode) |
|---------------------|-------|---------------------|
| 60×80 (split-view)  | 1     | 5 (stacked) |
| 80×60 (half-screen) | 1     | 4 |
| 60×120 (portrait)   | 1     | 8 |
| 40×120 (phone SSH)  | 1     | 8 |
| 200×50 (wide)       | 2     | 2 (unchanged) |
| 300×80 (ultra-wide) | 9     | 9 (unchanged) |

## [0.6.7] — 2026-04-21

### Changed
- **BREAKING** — CLI flag renamed from `--panes-per-window` to `--max-panes`. The flag has always behaved as a cap (layouts never pad to a fixed count, and an explicit int just upper-bounds the auto selection); the old name only described one use-case. No deprecated alias — scripts passing `--panes-per-window` need a one-line update.
- **Readability floor raised to 70 × 15 cells** (was 60 × 15). Tuned so a 13–15" laptop full-screen terminal (160–200 cols) lands on exactly two total column slices — orchestrator on the left, project panes vertically stacked on the right, each at its widest possible width. Wider terminals (250×60 and above) still expand to multi-column project grids.

### Results on common terminals (n panes / window)
| Terminal            | 0.6.6 (60×15) | 0.6.7 (70×15) |
|---------------------|---------------|---------------|
| 80×24               | 1             | 1             |
| 120×40 (half-split) | 2             | 1             |
| 160×50 (13″)        | 2             | 2             |
| 200×50 (15″)        | 5             | 2             |
| 250×60 (27″)        | 7             | 5             |
| 300×80 (27″ 4K)     | 13            | 9             |

The new default intentionally favors wider panes over more panes on mid-size terminals; the per-session override (`cmcp zellij --max-panes N`) is the escape hatch for users who want to pack more.

## [0.6.6] — 2026-04-21

### Fixed
- **`pick_panes_per_window` greedy-break missed legitimate candidates.** The scan used to stop at the first `n` whose grid failed the readability floor, even though a larger `n` could pass — `pick_rows` flips from 1→2 rows mid-scan, widening per-pane columns. On a 200×50 terminal that meant auto returned 3 when 5 was the right answer. Scan now walks the full candidate range and returns the highest-n that clears the floor.
- **Stale help text.** `--panes-per-window` help still said "default: 4" on `up` / `tmux` / `zellij` — but since 0.6.4 the default has been `auto`. Updated to say "auto — terminal-size derived" across the three subcommands so users stop chasing a flag they've already got.

### Changed
- **Readability floor bumped to 60 cols × 15 rows** (was 40×10). The previous floor was tuned for raw `central-mcp watch` event lines (timestamps + ids, ~30-40 chars) but ignored the actual coding-agent content the pane renders underneath — file paths, command invocations, stack traces routinely push 50-80 cols. 60×15 keeps one dispatch worth of start+content+done visible without scrolling or hard-wrap.
- **Orch-aware column model** in `pick_panes_per_window`: the hub tab reserves one column for orchestrator, so pane width is `cols / (project_top_cols + 1)` rather than `cols / (n_top + 1)`. Slight refinement; typically produces the same n, occasionally permits one more pane on wide terminals.

### Results on common terminals
| Terminal | 0.6.5 (40×10 + greedy) | 0.6.6 (60×15 + full scan) |
|---|---|---|
| 80×24  | 2 | 1 |
| 120×40 | 6 | 2 |
| 200×50 | 8 | 5 |
| 250×60 | 12 | 7 |
| 300×80 | 12 | 13 |

## [0.6.5] — 2026-04-21

### Fixed
- **tmux layout widths mangled at attach time.** 0.6.4's orchestrator column + equal-width project grid computed sizes correctly, but `tmux new-session -d` defaulted to 80×24, and attach-time rescaling did not preserve those ratios — on a wide terminal you'd end up with the orchestrator taking ~36% width and a single project absorbing another 36% while the rest collapsed to ~12 cells each. `tmux.new_session` now accepts `width`/`height`, and `layout.ensure_session` passes the invoking terminal's dimensions via `shutil.get_terminal_size(fallback=(200, 50))` so the layout is built at its real size from the start. Verified with a new live E2E test (`test_orch_column_full_height_with_many_projects`) that dispatches orch + 9 projects on a 200×50 terminal and asserts the actual `list-panes` geometry.

### Removed
- 6 unnecessary unit tests identified in a suite audit. Removals were either (a) redundant with other tests that exercise the same behavior through a more realistic path, or (b) testing Python/stdlib defaults rather than central-mcp logic.
  - `tests/test_watch.py::TestTailBehavior::test_creates_log_path_when_missing` — simulated `pathlib.mkdir` without calling `watch.run`.
  - `tests/test_orchestration.py::TestDispatchHistory::test_single_project_history` — duplicated by `test_dispatch.py::test_dispatch_history_exposes_output_preview`.
  - `tests/test_orchestration.py::TestOrchestrationHistory::test_includes_timeline_and_per_project_stats` — duplicated by `test_dispatch.py::test_orchestration_history_recent_includes_output_preview` plus `test_dispatch_writes_start_and_complete_events`.
  - `tests/test_adapters.py::TestAdapterRegistry::test_every_valid_agent_has_an_adapter` — every per-agent `TestClaude`/`TestCodex`/etc. class already calls `get_adapter(name)`.
  - `tests/test_registry.py::test_add_default_agent_is_claude` — tested the Python default-parameter value, not registry behavior.
  - `tests/test_registry.py::test_write_creates_parent_dir` — tested `Path.mkdir(parents=True)` which is exercised transitively by every other test in the file.

Net test count: 219 (was 224; −6 audit, +1 E2E geometry).

## [0.6.4] — 2026-04-20

### Changed
- **`--panes-per-window` defaults to `auto`** (was the hardcoded `4`). When no value is supplied, central-mcp reads the current terminal's size and picks how many panes fit while keeping each pane above a readability floor (~40 cols × 10 rows). On a 120×40 laptop terminal that's typically 6–8; on a 200×50 wide screen it reaches 10–12. Pass an explicit integer to override.
- **Orchestrator gets its own full-height left column** on the first tab, sized to match one project column rather than forcing a 50% split. `orch + 1 project` still reproduces the classic 50/50, but `orch + 9 projects` now gives orch a ~17% column with a 2×5 project grid filling the remaining 83% — instead of the 0.6.3 flat layout that buried the orchestrator as one of six equal-width cells.

### Added
- `central_mcp.grid.pick_panes_per_window(term_size, min_pane_cols, min_pane_rows)` — the heuristic that backs the new auto default. Exposed as a public function for adapter/test use.
- Internal `_fill_orch_column_grid` (tmux) and `orch_first=True` branch on `_tab_kdl` (zellij) render the orchestrator-column-plus-project-grid layout. Overflow tabs (no orchestrator) keep the flat 0.6.3 grid.
- 7 new tests: 4 for `pick_panes_per_window` regimes (tiny terminal → 1, wide terminal packs more than narrow, `min_pane_cols` override) and 3 for the zellij orch-column (size attribute present, 50/50 with 1 project, overflow tab has no size attribute).

### Upgrading note
- The stale-session guard from 0.6.1 applies: running a 0.6.3 observation session with 0.6.4 installed will refuse to attach until you `cmcp down` (or pass `--force-recreate`). `cmcp upgrade` auto-teardown (0.6.3+) handles the common upgrade path for you.

## [0.6.3] — 2026-04-20

### Changed
- **Equal-width panes, no more 50% orchestrator lock.** The observation layer used to pin the orchestrator pane to 50% of the hub via tmux `main-vertical` / a zellij outer vertical split; projects then stacked in the remaining half. That gave a strong orchestrator bias and squeezed project panes whenever the count grew. 0.6.3 drops the special case — orchestrator is now just the first pane of the first tab, sharing width equally with its row mates. Users who want it larger can manually resize inside tmux/zellij.
- **Flat chunking across tabs.** Every tab / window holds up to `panes_per_window` panes now, not `panes_per_window - 1` for the hub. With `panes_per_window=4`, orchestrator + 3 projects fits in one tab (was: hub=3 + overflow=1). Drops a whole class of off-by-one arithmetic in the layout code.
- **Terminal-size-aware grid rows.** New `central_mcp.grid.pick_rows(n, term_size=None)` picks the target row count based on the invoking terminal's aspect ratio. On a typical wide screen (120×40, 200×50) it returns 2 — matching 0.6.2 behavior. On a narrow / tall terminal (SSH from phone, split pane) it bumps to 3+ so pane widths don't collapse. One-time measurement at session creation — resizes mid-session don't retrigger.
- **Orchestrator pane width in a 3-pane row is now equal across all three** (previously degraded to `[50%, 25%, 25%]` after repeated 50/50 splits). tmux splits now pass size percentages tuned for equal final widths; the size formula produces a max deviation of ~2 char cells across a 3-pane row due to whole-cell rounding, verified in tests.

### Added
- `central-mcp upgrade` now tears down any live observation session before replacing the binary. Previously a running `cmcp up` session would hold the old version's orchestrator + `central-mcp watch` children, so the upgrade "didn't take" from the user's POV until they manually ran `cmcp down`. `--check` is read-only and skips the teardown.
- `central_mcp.tmux.split_window_with_id(..., size_percent=N)` — wraps tmux's `-l N%` so callers can build layouts with exact equal-sized panes instead of relying on the 50/50 default.

### Internal
- `central_mcp.grid` module: `pick_rows` (row count picker) + `row_sizes` (top-row-heavy distribution helper). Covered by 10 unit tests.
- `layout.py` helpers renamed: `_fill_2row_grid` → `_fill_grid(rows=N)` (generalized), `_fill_row(target_cols=N)` split out for reuse. Both use size percentages to keep sibling panes equal.
- zellij: deleted `_hub_tab_kdl` and `_project_tab_kdl` in favor of a single `_tab_kdl(tab_name, panes, rows)` that renders every tab the same way.

### Upgrading note
- The old stale-session guard added in 0.6.1 applies: running a 0.6.2 observation session when 0.6.3 is installed will refuse to attach until you `cmcp down` (or pass `--force-recreate`). 0.6.3 takes this one step further by auto-tearing-down on `cmcp upgrade`, so the common upgrade path is now drop-in.

## [0.6.2] — 2026-04-20

### Changed
- **2-row wide-column pane layout** for both observation backends. The old zellij grid fixed `cols=2` and grew rows as panes were added (10 panes → 5 rows × 2 cols, very tall). The new `_tile_panes` helper fixes `rows=2` and grows columns instead (10 panes → 2 rows × 5 cols). On a wide screen this fills horizontal space cleanly instead of squashing each pane into a thin horizontal sliver.
- **Hub right-half switches to 2-row grid at 3+ project panes.** For 1–2 projects the hub keeps the legacy vertical stack on the right (main-vertical for tmux, single `split_direction="horizontal"` for zellij) — splitting the already-narrow right column into two would produce unreadably thin panes at that scale. At 3+ project panes the right half flips to the 2-row grid so columns grow horizontally.
- **tmux orchestration** now uses manual split-window calls anchored by pane ids rather than `select-layout tiled`. Added `central_mcp.tmux.split_window_with_id` (wraps tmux's `-P -F '#{pane_id}'`) to return the new pane's stable id so we can target specific panes for subsequent splits — necessary for building an exact 2-row × N-col layout that tiled can't produce.

### Internal
- New `central_mcp.layout._fill_2row_grid(target, wname, anchor_id, plans, messages)` helper that extends any anchor pane into a 2-row grid. Reused by both hub (anchor = right-half of orchestrator split) and overflow windows (anchor = pane 0).
- 4 new zellij layout tests covering the 2-row grid shape (4-pane 2×2, 10-pane 2×5 ordering, hub-with-3 grid activation, hub-with-2 legacy stack regression guard). All 205 tests pass.

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
