---
description: Every MCP tool central-mcp exposes — list_projects, dispatch, check_dispatch, token_usage, registry mutations, and workspace operations — with default behavior and parameter notes.
---

# MCP tools

central-mcp exposes the following MCP tools to the orchestrator. The full source of truth is [`server.py`](https://github.com/andy5090/central-mcp/blob/main/src/central_mcp/server.py); this page is a curated reference.

!!! note
    Auto-extraction of full signatures + docstrings from `server.py` is on the roadmap.

---

## Portfolio queries

### `list_projects(workspace=None)`
List registered projects in the current workspace by default. Pass `workspace="<name>"` for a specific one, or `workspace="__all__"` (alias `"*"`) for every project across all workspaces.

### `project_status(name)`
Registry info for one project — agent, path, workspace membership. `project_pulse` returns all of this too; use `project_status` when metadata is all you need, since it costs one file read and spawns no subprocesses.

### `project_pulse(name, commits=5, history=5, include_pr=True)` (0.15.0+)
What actually happened in a project, where it stands, and what's still live. Use it when returning to a project after time away, or when asked "what's the state of X?".

Unlike `dispatch_history` / `orchestration_history` — which only know about work that went *through* central-mcp — a pulse reads the repository itself, so direct commits, interactive agent sessions, and manual edits show up too.

Sections:

- `git`: branch, upstream `ahead` / `behind`, working-tree dirt (staged / unstaged / untracked / conflicted counts plus a bounded file sample), and the last `commits` commits
- `dispatches`: `in_flight`, `stale` (rows still marked running after hours — a crashed server never wrote their terminal state, so they're unfinished, not live), the last `history` outcomes with prompts and previews, and all-time counts
- `sessions`: resumable agent conversations, for agents whose adapter can enumerate them
- `pull_requests`: open PRs via `gh` — the only network call, so pass `include_pr=False` when sweeping many projects
- `ledger` (0.20.0+): the project's recorded *intent* — `next_step` (with who recorded it and how long ago) and `drift.state` (`current` · `behind` · `empty` · `unknown`). Drift compares the ledger's watermark against commits, agent-session activity, and dirty-file mtimes, so a long session that produced no commit still registers. Computed here, never stored, so it can't go stale.

Each section degrades independently and carries a `reason` when unavailable; a missing section never means "nothing happened". Nothing is stored — every call recomputes from source.

### `project_note(note, name=None, cwd=None, next_step=None, source="agent")` (0.20.0+)
Record what was done, what was left, and what comes next — the durable half of the PM loop. `project_pulse` reads the repository for what is *true*; this stores what was *meant*, which no amount of reading git can recover.

Pass `name`, or `cwd` (any path inside the project) when the caller knows where it is but not what the project is registered as. With neither, the server's own working directory is used — a session opened inside a project inherits it.

Call it at the end of any stretch of real work, **including work that never went through `dispatch`**; when something you learn changes the plan; and above all when an approach is abandoned. *"Tried X, it fails because Y"* leaves no commit, no diff, and no trace of any kind — it is the one class of knowledge guaranteed lost otherwise.

`source` is `"agent"` (recording your own work) or `"user"` (writing down what the human said). Those are the only two: there is no `inferred`, because an entry synthesized from commit history would be indistinguishable from a first-hand record, and the ledger's whole value is that you can trust what it says.

Entries land in `~/.central-mcp/projects/<name>/STATUS.md` — plain markdown, append-only, safe to edit by hand.

### `orchestration_history(workspace=None, include_archives=False)`
Portfolio-wide snapshot: in-flight dispatches + recent milestones + per-project counts (dispatched / succeeded / failed / cancelled).

### `portfolio_digest(workspace=None, since_hours=24, quiet_days=7, include_quota=True)` (0.17.0+)
Pre-rendered portfolio summary — the push report of the Portfolio PM track. Returns structured sections plus `digest_markdown`, which callers forward **verbatim**: the format is fixed server-side (same reasoning as `token_usage.summary_markdown`) so the report looks identical whether a Hermes cron posts it to Telegram, a plain crontab pipes `cmcp digest` into a notifier, or a terminal orchestrator answers a "recap everything" ask.

Pulse-powered, so unlike `orchestration_history` it counts work that never went through central-mcp. Sections:

- `active` — projects with activity inside the window: commits (with the latest subject), dispatch ✅/❌ counts, in-flight count, uncommitted files
- `warnings` — failed dispatches in the window, dispatches stuck in `running` for hours (unfinished, not live), and quiet projects with uncommitted work sitting in them past `quiet_days`
- `quiet` — everything else, longest-idle first
- `quota` — compact per-agent subscription windows

`since_hours=24` for the daily report, `168` for weekly; `workspace` follows `list_projects` semantics. Nothing is stored — scheduling and alert watermarks belong to the caller.

### `token_usage(period="today", project=None, workspace=None, group_by="project", include_quota=True, include_summary=True)`
Token aggregation across all projects.

- `period`: `today` / `week` / `month` / `all`
- `group_by`: `project` / `agent` / `source`
- `include_quota` (default True): adds per-agent subscription quota windows
- `include_summary` (default True): adds a pre-rendered HUD-style markdown block (`summary_markdown`) ready to paste into a chat reply

---

## Dispatch lifecycle

### `dispatch(name, prompt, agent=None, model=None, ...)`
Run a one-shot agent in the project's cwd. **Non-blocking** — returns a `dispatch_id` in <100ms.

Pass `name="@workspace"` to fan-out the prompt to every project in that workspace at once (returns a list of `dispatch_id`s).

### `check_dispatch(dispatch_id)`
Poll a dispatch's status: `running` / `complete` / `error` / `cancelled`. Returns full output once complete. While the dispatch runs, the response carries `output` — the same block `tail_dispatch` returns — so a poller can tell a working dispatch from a silent one without a second call.

### `tail_dispatch(dispatch_id, since=None, max_lines=50)` (0.21.0+)
The lines a dispatch has printed so far, while it is still running. `check_dispatch` returns output only after the agent exits; this reads the per-line `output` events from the project's `dispatch.jsonl`.

Returns `lines` (oldest first; each has `ts`, `stream`, `agent`, `text`), `skipped`, `next_since`, `status`, and `output`. Pass `next_since` back as `since` to get only newer lines. When more than `max_lines` are new, you get the newest and `skipped` counts the rest; the cursor moves past them.

The `output` block describes activity as fact, not verdict:

| `state` | Meaning |
|---|---|
| `streaming` | Output arrived within the last 15 minutes. |
| `quiet` | Output arrived before, none for 15 minutes or longer. The one state that suggests a stuck dispatch. |
| `no_output_yet` | Nothing printed so far. |
| `exit_only` | Nothing printed so far, by an agent that prints only when it exits. Silence is its normal state. |

Which agents are `exit_only` is measured from dispatch logs, not taken from vendor documentation: claude printed nothing before exit in 43 of 43 dispatches longer than 20 seconds, while codex, gemini and opencode print as they run. Agents with too few samples are left unmeasured and are never judged. The 15-minute threshold sits above the longest silence seen in a dispatch that then succeeded (660 seconds).

The read is backward from the end of the log and stops at the cursor, so its cost follows the amount of new output, not the size of the log. Only the live log is read.

### `cancel_dispatch(dispatch_id)`
Abort a running dispatch.

### `list_dispatches(status=None, since=None)`
All active + recently completed dispatches. Rows carry `ok` and `finished_at` (0.17.0+).

- `status`: `running` / `complete` / `error` / `timeout` / `cancelled`, or the alias `failed` (anything that ended badly; cancelled is deliberate and excluded)
- `since`: ISO 8601 — only dispatches whose `finished_at` is *strictly* later; running rows always pass

Together they back a stateless failure watch: a resident agent calls `list_dispatches(status="failed", since=<watermark>)` on a schedule, alerts on what comes back, and advances its watermark to the max `finished_at` it saw. The strict filter means an unchanged watermark never re-alerts — and the watermark lives with the subscriber, not with central-mcp.

### `dispatch_history(name, limit=20)`
Last N dispatches for one project, with `prompt_preview` and `output_preview` slices. Reads the same log as `project_pulse`'s `dispatches` section, but goes as deep as you ask — the pulse deliberately shows only the last few, alongside git and session context. Briefing → pulse; digging → this.

---

## Registry mutations

### `add_project(name, path, agent=None, workspace=None, ...)`
Register a project.

### `remove_project(name)`
Deregister.

### `update_project(name, **fields)`
Edit registry fields without re-registering.

### `reorder_projects(order)`
Reorder the project list — affects the order panes appear in `cmcp up`.

---

## Sessions (where supported)

### `list_project_sessions(name)`
Agent-side conversation sessions. Currently supported for Claude Code and Codex.

---

## User preferences

### `get_user_preferences()`
Read `~/.central-mcp/user.md` content + scaffold examples for prompting.

### `update_user_preferences(content)`
Overwrite `~/.central-mcp/user.md`.

---

## How the orchestrator is told to use these

The runtime guidance lives in [`src/central_mcp/data/AGENTS.md`](https://github.com/andy5090/central-mcp/blob/main/src/central_mcp/data/AGENTS.md) and is shipped to `~/.central-mcp/AGENTS.md` on first launch. The MCP server also injects a compact summary as part of its `instructions` payload, so MCP clients see the same guidance.

---

## Experimental: MCP Tasks wire (0.13.0+)

Set `CENTRAL_MCP_TASKS=1` in the server's environment and central-mcp additionally serves the MCP Tasks protocol — `tasks/get`, `tasks/cancel`, and `tasks/result` — backed by the exact same dispatch state as the tools above. The `taskId` is the `dispatch_id` returned by `dispatch`, so a Tasks-speaking MCP client can drive a dispatch through the protocol's native polling lifecycle instead of calling `check_dispatch`.

- `tasks/get` returns the task object (`working` / `completed` / `failed` / `cancelled`, with `pollInterval: 3000`).
- `tasks/result` returns the final output once terminal, and an error while still running.
- `tasks/list` is deliberately not served — the 2026-07-28 MCP release removes it; `list_dispatches` covers the need.

`check_dispatch` / `cancel_dispatch` are unchanged either way — the extension is an additional wire shape over the same state, not a replacement. Flag off (the default) leaves the server byte-identical to before. See the [roadmap's MCP Tasks alignment section](ROADMAP.md#mcp-tasks-alignment) for where this is headed.
