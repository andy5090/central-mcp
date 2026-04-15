# central-mcp — orchestrator instructions

This directory is **central-mcp**, a multi-project orchestration hub. If you are a coding agent (Claude Code, Codex, Cursor, Gemini, etc.) reading this, **you are the orchestrator**, not the sole worker.

## What central-mcp is

An MCP server that manages a registry of coding-agent projects. Every `dispatch_query` call spawns the configured agent CLI as a one-shot non-interactive subprocess in the project's working directory and returns its full stdout to you over MCP. There is no long-lived pane to watch or keep alive — each dispatch is a fresh process that runs, writes its response, and exits.

## How to use it

When the user mentions "my projects", status, or dispatching work, call the `central` MCP tools — **do not** read files or run shell commands instead:

- `list_projects` — see what projects this hub manages
- `project_status` — the registry entry for one project (metadata only)
- `dispatch_query` — **run the agent non-interactively** in the project's cwd and get its response
- `add_project` / `remove_project` — edit the registry

`dispatch_query` is SYNCHRONOUS. It blocks until the subprocess exits (or the timeout fires) and returns `{ok, output, stderr, exit_code, duration_sec, project, agent, command}`. READ the `output` field and summarize or quote the response to the user in the same turn. Do not say "dispatched" and stop — the response is already in your return value.

If the user names a project that is not yet registered ("add ~/Projects/new-app"), call `add_project` yourself. Default `agent` to `claude` unless the user specifies otherwise.

Claude dispatches resume the most recent conversation in the project's cwd automatically (via `--continue`). Codex and Gemini dispatches are stateless — each call is a fresh context.

## When you are working INSIDE central-mcp's own source

If the user asks you to edit central-mcp's code itself (files under `src/central_mcp/`, etc.), switch modes: now you are a normal engineer working on this Python project. Use the file tools directly; the MCP hub tools are for managing *other* projects, not this one.
