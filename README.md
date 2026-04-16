# central-mcp

**Orchestrator-agnostic MCP hub for dispatching to multiple coding agents.**

One MCP server turns any MCP-capable client (Claude Code, Codex CLI, Cursor, Gemini CLI, …) into a control plane for your portfolio of coding-agent projects. Ask in natural language, and the orchestrator routes the request to the right project's agent — non-blocking, with results reported back asynchronously.

## Why

You probably use more than one coding agent. Each has its own terminal, its own session, its own logs. Switching between them is friction, and there is no shared view of *what answered what*.

`central-mcp` gives you one hub:

- **Dispatch** prompts to any project's agent and get responses via MCP
- **Parallel work** — dispatch to multiple projects and keep talking while they run
- **Manage** the registry with `add_project` / `remove_project`
- **Orchestrate** from any MCP-capable client — never locked to one

Every dispatch is a fresh subprocess in the project's cwd (e.g. `claude -p "..." --continue`). No long-lived processes, no screen scraping, no tmux dependency on the critical path.

## Design principles

1. **Orchestrator-agnostic.** MCP tools are the canonical surface. Any MCP client can be the orchestrator.
2. **Non-blocking dispatch.** `dispatch` returns a `dispatch_id` in <100ms. A background subagent polls for results. The conversation never freezes.
3. **Dispatch-router preamble.** The orchestrator is instructed to be a pure router — parse the project name, call `dispatch`, move on. No deliberation about which tool to use, no direct file/shell access. This minimizes LLM reasoning latency to ~1-2 seconds per turn.
4. **File-based state.** `registry.yaml` is the single source of truth.

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

# 4. Launch the orchestrator
central-mcp run
```

Inside the orchestrator session, speak naturally:

- *"Add ~/Projects/my-app to the hub, agent=claude."*
- *"What projects do I have?"*
- *"Send this to my-app: add error handling to the auth module."*
- *"Also send to gluecut-dawg: summarize the project structure."*

The orchestrator calls `dispatch` for each request and **continues the conversation immediately** — you don't wait. A background subagent polls every 3 seconds and reports each result as it arrives. Multiple dispatches run in parallel.

## MCP tools

`central-mcp` exposes 8 tools under the server name `central`:

| Tool | Blocking? | Purpose |
|---|---|---|
| `list_projects` | sync | Enumerate the registry. |
| `project_status` | sync | Metadata for one project. |
| `dispatch` | **<100ms** | Send a prompt to a project's agent. Returns `dispatch_id` immediately. |
| `check_dispatch` | sync | Poll a dispatch — `running` / `complete` / `error` with full output. |
| `list_dispatches` | sync | All active + recently completed dispatches. |
| `cancel_dispatch` | sync | Abort a running dispatch. |
| `add_project` | sync | Register a new project. Auto-trusts codex directories. |
| `remove_project` | sync | Unregister a project. |

### How dispatch works

```
dispatch("my-app", "add error handling to auth")
  → subprocess.Popen(["claude", "-p", "...", "--continue"], cwd="~/Projects/my-app")
  → returns {dispatch_id: "a1b2c3d4"} in <100ms
  → background thread captures stdout when process exits
  → check_dispatch("a1b2c3d4") → {status: "complete", output: "...", duration_sec: 45}
```

| Agent | Non-interactive invocation |
|---|---|
| `claude` | `claude -p "<prompt>" --continue` (resumes cwd conversation) |
| `codex` | `codex exec "<prompt>"` (stateless) |
| `gemini` | `gemini -p "<prompt>"` (stateless) |
| `cursor` | `cursor-agent -p "<prompt>" --resume` (resumes last session) |

### Performance tip: use a faster model for the orchestrator

The orchestrator's job is just routing — it doesn't need top-tier reasoning. Switching to a faster model cuts per-turn latency dramatically while the sub-agents (which do the actual work) stay on the best available model:

| Orchestrator client | Recommended model | How to switch |
|---|---|---|
| Claude Code | Sonnet (`/model sonnet`) | ~1-2s/turn vs ~5-8s on Opus |
| Codex CLI | `gpt-5.3-codex-spark` (default) | already fast |
| Gemini CLI | (default) | already fast |

## CLI reference

```
central-mcp                        # no-arg → run MCP server on stdio
central-mcp serve                  # same, explicit
central-mcp run [--agent X] [--pick] [--bypass]  # launch orchestrator
central-mcp install CLIENT         # register with claude | codex | cursor
central-mcp alias [NAME]           # short-name symlink (default: cmcp)
central-mcp unalias [NAME]
central-mcp init [PATH]            # scaffold registry.yaml (default: ~/.central-mcp)
central-mcp add NAME PATH [--agent claude|codex|gemini|cursor|shell]
central-mcp remove NAME
central-mcp list                   # one-line registry dump
central-mcp brief                  # orchestrator-ready markdown snapshot
central-mcp up                     # optional tmux observation (one pane per project)
central-mcp down                   # kill observation session
```

## Optional observation layer

`central-mcp up` creates a tmux session `central` with one interactive pane per project. Cycle panes with `Ctrl+b n` / `Ctrl+b <digit>`. This is **purely visual** — the MCP dispatch path never reads from or writes to these panes. Kill with `central-mcp down` without affecting anything.

## Registry resolution

Three-level cascade:

1. `$CENTRAL_MCP_REGISTRY` (explicit override)
2. `./registry.yaml` in cwd (per-project override)
3. `$HOME/.central-mcp/registry.yaml` (global default)

The registry is per-user state — never commit it.

## Changing the orchestrator

```bash
central-mcp run --pick         # re-run picker, save new choice
central-mcp run --agent codex  # one-off override
$EDITOR ~/.central-mcp/config.toml
```

## Permission bypass

```bash
central-mcp run --bypass
```

| Agent | Flag appended |
|---|---|
| Claude Code | `--dangerously-skip-permissions` |
| Codex CLI | `--dangerously-bypass-approvals-and-sandbox` |
| Gemini CLI | `--yolo` |

## Environment variables

- `CENTRAL_MCP_HOME` — user-state dir (default: `~/.central-mcp`)
- `CENTRAL_MCP_REGISTRY` — registry path override

## License

MIT (planned).
