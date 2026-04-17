# central-mcp

**Orchestrator-agnostic MCP hub for dispatching to multiple coding agents.**

One MCP server turns any MCP-capable client (Claude Code, Codex CLI, Gemini CLI, opencode, …) into a control plane for your portfolio of coding-agent projects. Ask in natural language, and the orchestrator routes the request to the right project's agent — non-blocking, with results reported back asynchronously.

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
2. **Non-blocking dispatch.** `dispatch` returns a `dispatch_id` in <100ms. Results arrive asynchronously. The conversation never freezes.
3. **Dispatch-router preamble.** The orchestrator is instructed to be a pure router — parse the project name, call `dispatch`, move on. This minimizes LLM reasoning latency to ~1-2 seconds per turn.
4. **File-based state.** `registry.yaml` is the single source of truth.

## Status

Pre-release. Install from a local checkout with `uv tool install --editable .`.

## Quickstart

Requires [`uv`](https://docs.astral.sh/uv/). (`tmux` only if you want the optional observation layer.)

```bash
# 1. Clone and install (editable, dev mode)
git clone https://github.com/andy5090/central-mcp.git ~/Projects/central-mcp
cd ~/Projects/central-mcp
uv tool install --editable .

# 2. Scaffold an empty registry at ~/.central-mcp/registry.yaml
central-mcp init

# 3. Register central-mcp with your MCP client(s) — once per client
central-mcp install claude    # adds to Claude Code MCP config
central-mcp install codex     # patches ~/.codex/config.toml
central-mcp install gemini    # patches ~/.gemini/settings.json
central-mcp install opencode  # patches ~/.config/opencode/opencode.json

# 4. Launch the orchestrator
central-mcp run
```

Inside the orchestrator session, speak naturally:

- *"Add ~/Projects/my-app to the hub, agent=claude."*
- *"What projects do I have?"*
- *"Send this to my-app: add error handling to the auth module."*
- *"Also send to gluecut-dawg: summarize the project structure."*

The orchestrator calls `dispatch` for each request and **continues the conversation immediately** — you don't wait. Results arrive through three channels:

- **Piggyback (automatic):** every MCP tool response includes a `completed_dispatches` array with any results that finished since the last call.
- **Background poll (best-effort):** a subagent polls `check_dispatch` every 3 seconds and reports automatically when done.
- **User-driven check (100% reliable):** ask "any updates?" anytime.

Multiple dispatches run in parallel.

## MCP tools

`central-mcp` exposes 10 tools under the server name `central`:

| Tool | Blocking? | Purpose |
|---|---|---|
| `list_projects` | sync | Enumerate the registry. |
| `project_status` | sync | Metadata for one project. |
| `dispatch` | **<100ms** | Send a prompt to a project's agent. Supports per-dispatch agent override and fallback chain. Returns `dispatch_id` immediately. |
| `check_dispatch` | sync | Poll a dispatch — `running` / `complete` / `error` with full output. |
| `list_dispatches` | sync | All active + recently completed dispatches. |
| `cancel_dispatch` | sync | Abort a running dispatch. |
| `dispatch_history` | sync | Persistent history of past dispatches (survives restarts). |
| `add_project` | sync | Register a new project. Validates agent name. Auto-trusts codex dirs. |
| `update_project` | sync | Change an existing project's agent, description, tags, bypass, or fallback. |
| `remove_project` | sync | Unregister a project. |

### How dispatch works

```
dispatch("my-app", "add error handling to auth")
  → subprocess.Popen(["claude", "-p", "...", "--continue"], cwd="~/Projects/my-app")
  → returns {dispatch_id: "a1b2c3d4"} in <100ms
  → background thread captures stdout when process exits
  → check_dispatch("a1b2c3d4") → {status: "complete", output: "...", duration_sec: 45}
```

### Supported agents

| Agent | Non-interactive invocation | Bypass flag |
|---|---|---|
| `claude` | `claude -p "<prompt>" --continue` | `--dangerously-skip-permissions` |
| `codex` | `codex exec "<prompt>"` | `--dangerously-bypass-approvals-and-sandbox` |
| `gemini` | `gemini -p "<prompt>"` | `--yolo` |
| `droid` | `droid exec "<prompt>"` | `--skip-permissions-unsafe` |
| `opencode` | `opencode run "<prompt>" --continue` | `--dangerously-skip-permissions` |

Agent names are validated at registration time — typos like `cursor-agent` are caught immediately, not at dispatch time.

### Switching agents mid-project

You can change a project's registered agent any time — useful when a given codebase turns out to pair better with a different CLI:

```
update_project(name="my-app", agent="codex")
```

`update_project` also accepts `description`, `tags`, `bypass`, and `fallback` — omitted fields stay untouched. Switching to `codex` auto-adds the project dir to `~/.codex/config.toml` trust list.

### One-shot agent override

Sometimes you want to route *one* task to a different agent without mutating the registry — e.g. a design-heavy task goes to a design-strong agent while the project stays on its usual one:

```
dispatch(name="my-app", prompt="...", agent="codex")
```

The registry entry is untouched. Next dispatch without `agent=` goes back to the project's saved agent.

### Fallback chain on failure

If the primary agent exits non-zero (rate limit, token cap, crash), central-mcp can transparently retry with a backup:

```
# per-dispatch (not persisted):
dispatch(name="my-app", prompt="...", fallback=["codex", "gemini"])

# save a default for this project:
update_project(name="my-app", fallback=["codex", "gemini"])
```

The result reports which agent actually produced output (`agent_used`), whether a fallback was triggered (`fallback_used`), and the full list of attempts. Timeouts are *not* retried — the user should see them directly rather than burn the whole chain on a stuck agent.

Pass `fallback=[]` to explicitly disable the saved chain for a one-shot dispatch.

### Per-project bypass mode

On the first dispatch to a project, central-mcp asks: *"Run with full permissions (bypass) or restricted?"* The choice is saved to `registry.yaml` for all future dispatches. Change it anytime by passing `bypass=true` or `bypass=false` explicitly.

If bypass=false and the agent hits a permission wall, the orchestrator will suggest either re-dispatching with bypass=true or using the tmux observation layer for interactive approval.

### Dispatch history

Every completed dispatch is logged to `~/.central-mcp/history/<project>.jsonl` — survives server restarts. Query with:

```
dispatch_history()                # last 10 across all projects
dispatch_history(name="my-app")   # last 10 for one project
dispatch_history(n=50)            # last 50
```

### Performance tip: use a faster model for the orchestrator

The orchestrator's job is just routing — it doesn't need top-tier reasoning:

| Orchestrator client | Tip |
|---|---|
| Claude Code | `/model sonnet` — ~1-2s/turn vs ~5-8s on Opus |
| Codex CLI | Use a lighter model (e.g. `-spark` variant) via `/model` or `config.toml` |
| Gemini CLI | Use Flash instead of Pro if available via model config |
| opencode | Select a faster model via `-m provider/model` or in `opencode.json` |

The sub-agent model is independent — each `dispatch` spawns its own process with whatever model the project's agent defaults to.

## CLI reference

```
central-mcp                        # no-arg → run MCP server on stdio
central-mcp serve                  # same, explicit
central-mcp run [--agent X] [--pick] [--bypass]  # launch orchestrator
central-mcp install CLIENT         # register with claude | codex | gemini | opencode
central-mcp alias [NAME]           # short-name symlink (default: cmcp)
central-mcp unalias [NAME]
central-mcp init [PATH]            # scaffold registry.yaml (default: ~/.central-mcp)
central-mcp add NAME PATH [--agent claude|codex|gemini|droid|opencode]
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

## Environment variables

- `CENTRAL_MCP_HOME` — user-state dir (default: `~/.central-mcp`)
- `CENTRAL_MCP_REGISTRY` — registry path override

## Development

```bash
uv tool install --editable .
uv run --group dev pytest             # 97 unit tests (fast, no real CLIs)
uv run --group dev pytest -m live     # 15 live tests — shell out to real agent binaries
                                      # (claude/codex/gemini/droid); each case skips
                                      # cleanly if that binary isn't on PATH
```

## License

MIT (planned).
