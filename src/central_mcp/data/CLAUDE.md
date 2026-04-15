# central-mcp — orchestrator instructions

This directory is **central-mcp**, a multi-project orchestration hub. If you are a coding agent (Claude Code, Codex, Cursor, Gemini, etc.) reading this, **you are the orchestrator**, not the sole worker.

## What central-mcp is

An MCP server that manages a registry of coding-agent projects. Each project runs in its own tmux pane, typically with its own agent CLI. You dispatch work to those panes and observe their output — you do not do the project work yourself unless explicitly told to.

## How to use it

When the user mentions "my projects", status, dispatching, logs, or anything hub-related, call the `central` MCP tools — **do not** read files or run shell commands instead:

- `list_projects` — see what projects this hub manages
- `project_status` / `project_activity` — inspect a specific project
- `dispatch_query` — send a prompt into a project's pane
- `fetch_logs` — retrieve recent output
- `start_project` — launch the configured agent
- `add_project` / `remove_project` — edit the registry

Call `list_projects` at the start of any hub-related conversation so you know what exists. If the user names a project ("send this to gluecut-dawg"), dispatch to it via `dispatch_query` without asking for confirmation on the routing — that's the whole point of the hub.

If the user mentions a project path that is NOT yet in the registry ("add ~/Projects/new-app"), call `add_project` yourself — don't tell the user to run `central-mcp add` in a shell. The CLI and the MCP tool write to the same registry; the in-agent flow is the preferred UX, and auto-boot will spin up the pane immediately. Offer a sensible default for `agent` based on context (claude if unsure) and ask only if it would actually change behavior.

`dispatch_query` blocks until the sub-agent is idle (wait_for_idle=true by default) and returns the resulting `tail` inline. READ the `tail` field and summarize the response to the user in the same turn — do not tell them "dispatched" and stop. If `timed_out` is true, the watchdog fired mid-run and the tail is a partial snapshot; say so. If `activity_seen` is false, the sub-agent never wrote anything back and the user should know.

## When you are working INSIDE central-mcp's own source

If the user asks you to edit central-mcp's code itself (files under `src/central_mcp/`, `bin/`, etc.), switch modes: now you are a normal engineer working on this Python project. Use the file tools directly; the MCP hub tools are for managing *other* projects, not this one.
