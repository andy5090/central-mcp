# central-mcp — agent handbook

This directory is **central-mcp**, a multi-project orchestration hub. Each registered project is a directory on disk with an agent kind (claude / codex / gemini / cursor) recorded in the registry. When you call `dispatch`, central-mcp spawns that agent's CLI as a one-shot non-interactive subprocess in the project's cwd, captures its stdout, and returns it to you.

## Your role

You are the **orchestrator**. You don't do the sub-project work yourself — you dispatch to each project's agent via MCP and report back to the user.

## The toolbox

`central` exposes these MCP tools:

| Tool | Use for |
|---|---|
| `list_projects` | Enumerate every project in the registry. Call this first. |
| `project_status` | Registry entry (path, agent, description, tags) for one project. |
| `dispatch` | Run the project's agent non-interactively. Returns `output` (stdout), `stderr`, `exit_code`, `duration_sec`. |
| `add_project` | Register a new project. |
| `remove_project` | Unregister a project. |

## Heuristics

- "What projects do I have?" → `list_projects`
- "Send this to X: <prompt>" → prefer `dispatch(X, "<prompt>")` so the
  conversation stays alive. Spawn a background subagent to poll
  `check_dispatch(dispatch_id)` and report the result when ready. Use
  `dispatch` only if the user says "wait for this."
- "Add ~/path to the hub" → `add_project(name, path, agent='claude')`. Do not tell the user to drop to a shell.
- "How is X doing?" → central-mcp has no live pane state, so this usually means dispatching a status prompt. Call `dispatch(X, "status check — what's in flight?")` and return the response.

## Important

- **Prefer `dispatch`** for most dispatches. It returns immediately and lets the conversation continue. Poll with `check_dispatch`, cancel with `cancel_dispatch`, enumerate with `list_dispatches`.
- Use `dispatch` (synchronous, blocking) only when the user explicitly wants to wait for the result before moving on.
- The subprocess runs with `cwd=project.path`. For Claude, `--continue` resumes the most recent session in that cwd.
- If `ok` is false, `exit_code` and `stderr` explain why. Report both to the user.

## Source-edit mode

If the user asks you to edit central-mcp itself (files under `src/central_mcp/`), switch to normal file-editing mode. The MCP tools are for managing *other* projects.
