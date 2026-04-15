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

# 2. Scaffold an empty registry (writes to ~/.central-mcp/registry.yaml)
central-mcp init

# 3. Connect your orchestrator client ONCE (pick whichever you prefer)
central-mcp install claude    # adds to Claude Code MCP config
central-mcp install codex     # patches ~/.codex/config.toml
central-mcp install cursor    # patches ~/.cursor/mcp.json
```

That's it. Start your chosen client and manage the hub in natural
language from there — you don't need to drop back to a shell to add
projects or change anything. For example:

- *"Add ~/Projects/my-app to the hub and run Claude Code on it."*
- *"What projects do I have? Send the latest design doc to my-app."*
- *"How is gluecut-dawg doing right now?"*

The orchestrator will call `add_project`, `dispatch_query`,
`project_status`, etc. on your behalf. The hub auto-creates the tmux
layout on the first mutating MCP call and auto-launches each project's
configured agent. Run `tmux attach -t central` in a real terminal to
watch the panes live whenever you want to look over its shoulder.

### Optional manual controls

```bash
central-mcp up      # eagerly create tmux sessions (not required — lazy-boot handles it)
central-mcp down    # kill every session the registry references
central-mcp list    # one-line dump
central-mcp brief   # orchestrator-ready markdown snapshot
```

`add_project` (via MCP or CLI) also auto-boots the new pane on the fly, so
you can grow the hub during a session without tearing anything down.

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

## Registry resolution

`central-mcp` resolves the registry path with a three-level cascade:

1. `$CENTRAL_MCP_REGISTRY` if set
2. `./registry.yaml` if it exists in the current directory (per-project override)
3. `$HOME/.central-mcp/registry.yaml` (the global default; created by `central-mcp init`)

The registry file is per-user state — never commit it. This repo's `.gitignore`
already excludes it.

## Environment variables

- `CENTRAL_MCP_REGISTRY` — override the registry path (takes precedence over the cascade)
- `CENTRAL_HUB_SPLIT` — `horizontal` (default) | `vertical` | `none` — hub window split direction
- `CENTRAL_MCP_AUTOSTART` — `1` (default) | `0` — auto-launch each project's agent when `up` creates a session

## License

MIT (planned).
