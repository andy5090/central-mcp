# central-mcp

**Orchestrator-agnostic MCP hub for managing and dispatching to multiple coding agents.**

One MCP server turns any MCP-capable client (Claude Code, Codex CLI, Cursor, Gemini CLI, …) into the control plane for your portfolio of coding-agent projects. List projects, inspect their state, dispatch prompts, and collect logs — all from whichever agent you happen to be using.

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
# 1. Clone and install (editable, dev mode)
git clone <repo> ~/Projects/central-mcp
cd ~/Projects/central-mcp
uv tool install --editable .

# 2. Scaffold an empty registry at ~/.central-mcp/registry.yaml.
#    This also tries to create a `cmcp` short-name symlink next to
#    central-mcp, unless something else with that name is already on PATH
#    (e.g. the unrelated PyPI package of the same name). Pass --no-alias
#    to skip, or run `central-mcp alias OTHER_NAME` later to pick a
#    different short name.
central-mcp init

# 3. Register central-mcp with your MCP client(s) — once per client
central-mcp install claude    # adds to Claude Code MCP config
central-mcp install codex     # patches ~/.codex/config.toml
central-mcp install cursor    # patches ~/.cursor/mcp.json

# 4. Launch the orchestrator. On first run central-mcp detects which
#    coding-agent CLIs you have installed and — if there's more than one —
#    prompts you to pick one. The choice is saved to
#    ~/.central-mcp/config.toml for next time.
central-mcp run
```

That's it. The chosen client starts in `~/.central-mcp/`, which `central-mcp run` scaffolds with an orchestrator preamble (`CLAUDE.md` / `AGENTS.md`) and a SessionStart hook that injects a live project brief. Manage the hub in natural language from there — no need to drop back to a shell:

- *"Add ~/Projects/my-app to the hub and run Claude Code on it."*
- *"What projects do I have? Send the latest design doc to my-app."*
- *"How is gluecut-dawg doing right now?"*

The orchestrator calls `add_project`, `dispatch_query`, `project_status`, etc. on your behalf. The hub auto-creates the tmux layout on the first mutating MCP call and auto-launches each project's configured agent. Run `tmux attach -t central` in a real terminal to watch the panes live whenever you want to look over its shoulder.

## What the orchestrator can do

`central-mcp` exposes eight MCP tools under the server name `central`. Any connected client will see them in its tool list:

| Tool | Purpose |
|---|---|
| `list_projects` | Enumerate everything in the registry. |
| `project_status` | Registry info + recent pane output for one project. |
| `project_activity` | `busy` / `recent` / `idle` classification + current process. |
| `dispatch_query` | Send a prompt into a project's pane as keystrokes. |
| `fetch_logs` | Retrieve recent pane output (live scrollback or persisted log file). |
| `start_project` | Launch the configured agent CLI in its pane. |
| `add_project` | Register a new project (auto-boots its tmux pane). |
| `remove_project` | Unregister a project. |

All tools honor ANSI stripping and secret-regex redaction by default — both can be opted out per-call.

## CLI reference

```
central-mcp                          # no-arg → run MCP server on stdio (what clients invoke)
central-mcp serve                    # same, explicit
central-mcp run [--agent X] [--pick] [--bypass]  # launch a coding-agent CLI as orchestrator
central-mcp install CLIENT           # register central-mcp with claude | codex | cursor
central-mcp alias [NAME]             # create a short-name symlink (default: cmcp), conflict-checked
central-mcp unalias [NAME]           # remove an alias previously created by `alias`
central-mcp init [PATH]              # scaffold empty registry.yaml (default: ~/.central-mcp)
central-mcp add NAME PATH [--agent …]  # register a project from the shell
central-mcp remove NAME
central-mcp list                     # one-line-per-project dump
central-mcp brief                    # orchestrator-ready markdown snapshot
central-mcp up                       # eagerly create tmux sessions (optional — lazy-boot handles it)
central-mcp down                     # kill every session the registry references
```

After running `central-mcp alias`, every command above also works as `cmcp …`.
The alias is an opt-in symlink, not a forced entry point — so users who already
have a different `cmcp` on their PATH (e.g. the unrelated PyPI package of the
same name) won't have it silently shadowed by installing central-mcp.

## Registry resolution

`central-mcp` resolves the registry path with a three-level cascade:

1. `$CENTRAL_MCP_REGISTRY` if set (explicit override)
2. `./registry.yaml` if it exists in the current directory (per-project override)
3. `$HOME/.central-mcp/registry.yaml` (the global default; created by `cmcp init`)

The registry file is per-user state — never commit it. This repo's `.gitignore` already excludes it.

## Changing the orchestrator agent

The first time you run `central-mcp run`, the CLI detects every coding
agent on your PATH, prompts you to pick one (if there's more than one),
and saves the choice to `~/.central-mcp/config.toml`. Every later launch
uses that preference silently — but prints the source of the choice so
you can always see what you're running:

```
orchestrator : Claude Code (claude)  [saved preference]
```

Three ways to change it:

```bash
central-mcp run --pick         # re-run the interactive picker, overwrite saved
central-mcp run --agent codex  # one-off override — does NOT touch the saved value
$EDITOR ~/.central-mcp/config.toml   # edit the file by hand
```

If the saved binary ever disappears from PATH, `run` prints a warning
and falls through to re-pick automatically.

## Permission bypass mode

`central-mcp run --bypass` launches the orchestrator in its "skip all
permission prompts" / yolo mode when the agent exposes one:

| Agent | Flag that gets appended |
|---|---|
| Claude Code | `--dangerously-skip-permissions` |
| Codex CLI | `--dangerously-bypass-approvals-and-sandbox` |
| Gemini CLI | `--yolo` |
| Cursor Agent | (not wired — warning printed) |

Use with intent. This is for turnkey sessions where you trust the
orchestrator to dispatch freely; individual project panes still enforce
whatever permission model you started them with.

## Environment variables

- `CENTRAL_MCP_REGISTRY` — override the registry path (takes precedence over the cascade)
- `CENTRAL_HUB_SPLIT` — `horizontal` (default) | `vertical` | `none` — hub window split direction
- `CENTRAL_MCP_AUTOSTART` — `1` (default) | `0` — auto-launch each project's agent when sessions are created

## License

MIT (planned).
