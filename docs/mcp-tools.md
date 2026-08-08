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

Each section degrades independently and carries a `reason` when unavailable; a missing section never means "nothing happened". Nothing is stored — every call recomputes from source.

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
Poll a dispatch's status: `running` / `complete` / `error` / `cancelled`. Returns full output once complete.

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
