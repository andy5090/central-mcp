# Changelog

All notable changes to central-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

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
