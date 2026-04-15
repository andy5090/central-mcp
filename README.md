# central-mcp

**Orchestrator-agnostic MCP hub for dispatching to multiple coding agents.**

One MCP server turns any MCP-capable client (Claude Code, Codex CLI, Cursor, Gemini CLI, …) into a control plane for your portfolio of coding-agent projects. Ask in natural language, and the orchestrator spawns the target project's agent as a non-interactive subprocess, captures its full response, and relays it back to you.

## Why

You probably use more than one coding agent. Each has its own terminal, its own session, its own logs. Switching between them is friction, and there is no shared view of *what answered what*.

`central-mcp` gives you one hub:

- **List** every project in your registry
- **Dispatch** a prompt to a specific project's agent and get the response back over MCP
- **Manage** the registry with `add_project` / `remove_project`
- **Orchestrate** from any MCP-capable client — never locked to one

Every dispatch is a fresh subprocess run in the project's cwd (e.g. `claude -p "..." --continue`). No tmux panes to keep alive, no long-lived processes to babysit, no screen scraping.

## Design principles

1. **Orchestrator-agnostic.** MCP tools are the canonical surface. Any MCP client can be the orchestrator.
2. **Subprocess dispatch.** `dispatch_query` runs the configured agent non-interactively, captures stdout, returns it. That's it.
3. **File-based state.** `registry.yaml` is the single source of truth.
4. **Thin.** Add only what real usage demands.

## Status

Pre-release. Install from a local checkout with `uv tool install --editable .`.

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/). (`tmux` only if you want the optional observation layer.)

```bash
# 1. Clone and install (editable, dev mode)
git clone <repo> ~/Projects/central-mcp
cd ~/Projects/central-mcp
uv tool install --editable .

# 2. Scaffold an empty registry at ~/.central-mcp/registry.yaml
central-mcp init

# 3. Register central-mcp with your MCP client(s) — once per client
central-mcp install claude    # adds to Claude Code MCP config
central-mcp install codex     # patches ~/.codex/config.toml
central-mcp install cursor    # patches ~/.cursor/mcp.json

# 4. Launch the orchestrator. First run detects which coding-agent CLIs
#    you have installed and (if multiple) prompts you to pick one.
central-mcp run
```

That's it. Inside the orchestrator session, speak naturally:

- *"Add ~/Projects/my-app to the hub, agent=claude."*
- *"What projects do I have?"*
- *"Send this to my-app: add error handling to the auth module and summarize what you changed."*

The orchestrator calls `add_project`, `dispatch_query`, etc. on your behalf. `dispatch_query` blocks until the sub-agent finishes writing and returns its full stdout so the orchestrator can quote or summarize the response in the same turn.

## What the orchestrator can do

`central-mcp` exposes five MCP tools under the server name `central`:

| Tool | Purpose |
|---|---|
| `list_projects` | Enumerate everything in the registry. |
| `project_status` | Return the registry entry for one project (metadata only). |
| `dispatch_query` | Run the project's agent non-interactively and return `{ok, output, stderr, exit_code, duration_sec, …}`. |
| `add_project` | Register a new project (no tmux pane created, no process spawned). |
| `remove_project` | Unregister a project. |

### How dispatch translates

| Agent | Invocation |
|---|---|
| `claude` | `claude -p "<prompt>" --continue` (resumes the project-cwd conversation) |
| `codex` | `codex exec "<prompt>"` (stateless, one-shot) |
| `gemini` | `gemini -p "<prompt>"` (stateless) |
| `cursor` | (not wired — cursor-agent's non-interactive mode not yet supported) |

The subprocess runs with `cwd` set to the project path. Every dispatch is captured and returned as the `output` field of the MCP response.

## CLI reference

```
central-mcp                        # no-arg → run MCP server on stdio (what clients invoke)
central-mcp serve                  # same, explicit
central-mcp run [--agent X] [--pick] [--bypass]  # launch a coding-agent CLI as orchestrator
central-mcp install CLIENT         # register central-mcp with claude | codex | cursor
central-mcp alias [NAME]           # create a short-name symlink (default: cmcp)
central-mcp unalias [NAME]         # remove an alias previously created by `alias`
central-mcp init [PATH]            # scaffold empty registry.yaml (default: ~/.central-mcp)
central-mcp add NAME PATH [--agent claude|codex|gemini|cursor|shell]
central-mcp remove NAME
central-mcp list                   # one-line-per-project dump
central-mcp brief                  # orchestrator-ready markdown snapshot
central-mcp up                     # optional tmux observation session — one interactive pane per project
central-mcp down                   # kill the observation session
```

## Optional observation layer

If you want to peek at each project's agent in real time (say, to watch a long-running task), `central-mcp up` creates a tmux session named `central` with one window `projects` and one interactive pane per registered project. Cycle panes with `Ctrl+b n` / `Ctrl+b <digit>`.

This layer is **purely visual** — it has no effect on MCP dispatch. `dispatch_query` never reads from or writes to those panes; it always spawns its own subprocess. Kill the session with `central-mcp down` (or let it run forever) without affecting anything the orchestrator does.

## Registry resolution

`central-mcp` resolves the registry path with a three-level cascade:

1. `$CENTRAL_MCP_REGISTRY` if set (explicit override)
2. `./registry.yaml` if it exists in the current directory (per-project override)
3. `$HOME/.central-mcp/registry.yaml` (the global default; created by `central-mcp init`)

The registry file is per-user state — never commit it. This repo's `.gitignore` already excludes it.

## Changing the orchestrator agent

The first time you run `central-mcp run`, the CLI detects every coding agent on your PATH, prompts you to pick one (if there's more than one), and saves the choice to `~/.central-mcp/config.toml`. Every later launch uses that preference silently — and prints the source of the choice so you always see what you're running:

```
orchestrator : Claude Code (claude)  [saved preference]
```

Three ways to change it:

```bash
central-mcp run --pick         # re-run the interactive picker, overwrite saved
central-mcp run --agent codex  # one-off override — does NOT touch the saved value
$EDITOR ~/.central-mcp/config.toml   # edit the file by hand
```

## Permission bypass mode

`central-mcp run --bypass` launches the orchestrator in its "skip all permission prompts" / yolo mode when the agent exposes one:

| Agent | Flag appended |
|---|---|
| Claude Code | `--dangerously-skip-permissions` |
| Codex CLI | `--dangerously-bypass-approvals-and-sandbox` |
| Gemini CLI | `--yolo` |
| Cursor Agent | (not wired — warning printed) |

## Environment variables

- `CENTRAL_MCP_HOME` — override the user-state dir (default: `~/.central-mcp`)
- `CENTRAL_MCP_REGISTRY` — override the registry path (takes precedence over the cascade)

## License

MIT (planned).
