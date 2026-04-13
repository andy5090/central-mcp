# central-mcp

**Orchestrator-agnostic MCP hub for managing and dispatching to multiple coding agents.**

`central-mcp` is a single MCP server that lets any MCP-capable client (Claude Code, Codex CLI, Cursor, Gemini CLI, ...) act as a central hub for your portfolio of coding-agent projects. List projects, inspect their state, dispatch prompts to them, and collect logs — all from whichever agent you happen to be using.

## Why

You probably use more than one coding agent. Each has its own terminal, its own session, its own logs. Switching between them is friction, and there is no shared view of *what is in flight where*.

`central-mcp` gives you one place to:

- **See** every project and its current status (`list_projects`, `project_status`)
- **Dispatch** a prompt to a specific project's agent (`dispatch_query`)
- **Collect** recent output from any project (`fetch_logs`)

The hub runs the sub-agents inside tmux panes, so you keep full visual access — the hub is a control layer, not a replacement for your terminal.

## Design principles

1. **Orchestrator-agnostic.** The server exposes plain MCP tools. Any MCP client can be the orchestrator.
2. **tmux as the runtime layer.** Each project lives in a tmux pane. The hub sends keys and captures output. No custom TUI.
3. **File-based state.** `registry.yaml` is the single source of truth.
4. **Thin.** Start with three tools. Add only what real usage demands.

## Status

Phase 0 — local prototype. Not yet published.

## Quickstart (Phase 0)

Requires [`uv`](https://docs.astral.sh/uv/) and `tmux`.

```bash
# 1. Clone
git clone <repo> ~/Projects/project-central
cd ~/Projects/project-central

# 2. Edit registry.yaml to describe your projects

# 3. Bring up tmux layout
./bin/central-up.sh
tmux attach -t central   # in a real terminal

# 4. Register the MCP server with your client of choice.
#    uv run takes care of the virtualenv and dependencies on first launch.
claude mcp add central -- \
    uv run --directory /Users/andy/Projects/project-central python -m central_mcp
```

See `examples/clients/` for Codex, Cursor, and other clients. Once published
to PyPI, the recommended form will be `uvx central-mcp` with zero setup.

## License

MIT (planned).
