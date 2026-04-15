"""Orchestrator preamble files written into the launch directory.

These mirror the top-level CLAUDE.md and AGENTS.md of the repo. Keep them
in sync by hand for now — canonical content lives here so that users who
installed via `uv tool install central-mcp` (non-editable) still get the
briefing when `central-mcp run` scaffolds their launch directory.
"""

from __future__ import annotations

CLAUDE_MD = """\
# central-mcp — orchestrator instructions

This directory is a **central-mcp launch directory**. If you are a coding agent (Claude Code, Codex, Cursor, Gemini, etc.) reading this, **you are the orchestrator**, not the sole worker.

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
"""

AGENTS_MD = """\
# central-mcp — agent handbook

This directory is a **central-mcp launch directory**, set up by `central-mcp run`. If you are an agent running a session from here (Codex, Claude Code, Cursor, Gemini, or any other MCP-capable CLI), read this first.

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
- "Add ~/path/to/project to the hub" → call `add_project` directly. Do not
  tell the user to drop to a shell. Pick a sensible `agent` default
  (claude if unsure) and mention the choice in your reply so the user
  can correct it. `add_project` auto-boots the tmux pane.
- Anything "hub-wide" (search, summary, multi-project) → start with `list_projects`, then iterate per-project

Do not paste entire logs back to the user unless asked. Summarize what happened.
"""

SETTINGS_JSON = """\
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "central-mcp brief"
          }
        ]
      }
    ]
  }
}
"""
