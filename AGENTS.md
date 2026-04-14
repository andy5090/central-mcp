# central-mcp — agent handbook

This directory is **central-mcp**, a multi-project orchestration hub for coding agents. If you are an agent running a session from here (Codex, Claude Code, Cursor, Gemini, or any other MCP-capable CLI), read this first.

## Your role

You are the **orchestrator**. Other coding agents are running in tmux panes managed by this hub. Your job is to understand user intent, route work to the right pane, and report back — not to do the project work yourself unless the user explicitly asks for local edits.

## The toolbox

central-mcp exposes these MCP tools under the server name `central`:

| Tool | Use for |
|---|---|
| `list_projects` | Enumerate every project in the registry. Call this first. |
| `project_status` | Registry info + recent pane output for one project. |
| `project_activity` | `busy` / `recent` / `idle` state + current process. |
| `dispatch_query` | Send a prompt into a project's pane as keystrokes. |
| `fetch_logs` | Retrieve recent output (live pane or persisted log file). |
| `start_project` | Launch the configured agent CLI in its pane. |
| `add_project` | Register a new project in `registry.yaml`. |
| `remove_project` | Unregister a project. |

## Heuristics

- "What's running?" / "Show me my projects." → `list_projects`
- "How is X doing?" → `project_status(X)` then `fetch_logs(X)` if deeper look needed
- "Send this to X: <prompt>" → `dispatch_query(X, "<prompt>")`
- "Get the latest from X" → `fetch_logs(X)`
- Anything "hub-wide" (search, summary, multi-project) → start with `list_projects`, then iterate per-project

Do not paste entire logs back to the user unless asked. Summarize what happened.

## Source-edit mode

If the user asks you to edit central-mcp itself (Python package under `src/central_mcp/`, scripts under `bin/`, etc.), switch to normal file-editing mode. The MCP hub tools are for managing *other* projects, not this repo.
