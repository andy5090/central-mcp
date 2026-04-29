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
Registry info for one project — agent, path, workspace membership.

### `orchestration_history(workspace=None, include_archives=False)`
Portfolio-wide snapshot: in-flight dispatches + recent milestones + per-project counts (dispatched / succeeded / failed / cancelled).

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

### `list_dispatches()`
All active + recently completed dispatches.

### `dispatch_history(name, limit=20)`
Last N dispatches for one project, with `prompt_preview` and `output_preview` slices.

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
