# central-mcp

**Orchestrator-agnostic MCP hub for managing and dispatching to multiple coding agents.**

One MCP server, any MCP-capable client (Claude Code, Codex CLI, Cursor, Gemini CLI, …) becomes the control plane for your portfolio of coding-agent projects. List projects, inspect their state, dispatch prompts, and collect logs — all from whichever agent you happen to be using.

## Why

You probably use more than one coding agent. Each has its own terminal, its own session, its own logs. Switching between them is friction, and there is no shared view of *what is in flight where*.

`central-mcp` gives you one hub:

- **See** every project and its current status
- **Dispatch** a prompt to a specific project's agent
- **Collect** recent output from any project
- **Orchestrate** from any MCP-capable client — never locked to one

Sub-agents run inside tmux panes so you keep full visual access; the hub is a control layer, not a replacement for your terminal.

## Design principles

1. **Orchestrator-agnostic.** MCP tools are the canonical surface. Any MCP client can be the orchestrator.
2. **tmux as the runtime layer.** Each project lives in a pane. Central dispatches keystrokes and captures output. No custom TUI.
3. **File-based state.** `registry.yaml` is the single source of truth.
4. **Thin.** Add only what real usage demands.

## Status

Pre-release — not yet on PyPI. Install from a local checkout with `uv tool install --editable .`.

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/) and `tmux`.

```bash
# 1. Clone and install (dev mode — editable)
git clone <repo> ~/Projects/central-mcp
cd ~/Projects/central-mcp
uv tool install --editable .

# 2. Scaffold a registry in the directory you want to manage projects from
#    (or just use the repo directory for now)
central-mcp init

# 3. Register the projects you want the hub to know about
central-mcp add gluecut-dawg ~/Projects/gluecut-dawg --agent claude

# 4. Bring up the tmux layout (creates panes, auto-launches agents)
central-mcp up
tmux attach -t central   # in a real terminal

# 5. Connect your orchestrator client ONCE (pick whichever you prefer)
central-mcp install claude    # adds to Claude Code MCP config
central-mcp install codex     # patches ~/.codex/config.toml
central-mcp install cursor    # patches ~/.cursor/mcp.json
```

Now start any of those clients and ask natural-language questions about your projects — the hub server will expose `list_projects`, `dispatch_query`, `fetch_logs`, `project_activity`, etc.

## CLI reference

```
central-mcp                       # no-arg → run MCP server on stdio
central-mcp serve                 # same, explicit
central-mcp up                    # create tmux sessions from registry.yaml
central-mcp down                  # kill every session the registry references
central-mcp list                  # one-line-per-project dump
central-mcp brief                 # orchestrator-ready markdown snapshot
central-mcp add NAME PATH [--agent claude|codex|gemini|cursor|shell] …
central-mcp remove NAME
central-mcp init [DIR]            # scaffold registry.yaml + .claude/settings.json
central-mcp install CLIENT [--dry-run]
```

## Environment variables

- `CENTRAL_MCP_REGISTRY` — override the registry.yaml path (default: `./registry.yaml`)
- `CENTRAL_HUB_SPLIT` — `horizontal` (default) | `vertical` | `none` — hub window split direction
- `CENTRAL_MCP_AUTOSTART` — `1` (default) | `0` — auto-launch each project's agent when `up` creates a session

## License

MIT (planned).
