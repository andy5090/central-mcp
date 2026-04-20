# central-mcp

<p align="center">
  <img src="docs/logo.png" alt="central-mcp logo" width="280"/>
</p>

[![PyPI version](https://img.shields.io/pypi/v/central-mcp)](https://pypi.org/project/central-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/central-mcp)](https://pypi.org/project/central-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Orchestrator-agnostic MCP hub for dispatching to multiple coding agents.**

> **Never stop. Run agents across every project in parallel — 10×, 100× your throughput.**

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

Available on [PyPI](https://pypi.org/project/central-mcp/).

## Quickstart

```bash
# Install uv if you don't have it yet (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> Or use pip: `pip install central-mcp`

(`tmux` only if you want the optional observation layer.)

```bash
# 1. Install central-mcp
uv tool install central-mcp

# 2. Launch — one command does everything
central-mcp
```

The first `central-mcp` run auto-creates `~/.central-mcp/registry.yaml` and registers central-mcp with every MCP client binary it finds on PATH (claude, codex, gemini, opencode). After that it launches the orchestrator in your preferred agent.

> **Manual install** if you want fine-grained control:
> - `central-mcp install all` — re-detect + register everywhere
> - `central-mcp install claude` — register with a single client
> - `central-mcp init` — create the registry without launching

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

`central-mcp` exposes 11 tools under the server name `central`:

| Tool | Blocking? | Purpose |
|---|---|---|
| `list_projects` | sync | Enumerate the registry. |
| `project_status` | sync | Metadata for one project. |
| `dispatch` | **<100ms** | Send a prompt to a project's agent. Supports per-dispatch agent override and fallback chain. Returns `dispatch_id` immediately. |
| `check_dispatch` | sync | Poll a dispatch — `running` / `complete` / `error` with full output. |
| `list_dispatches` | sync | All active + recently completed dispatches. |
| `cancel_dispatch` | sync | Abort a running dispatch. |
| `dispatch_history` | sync | Last N dispatches for **one project** (reads its jsonl log). |
| `orchestration_history` | sync | Portfolio-wide snapshot: in-flight + recent cross-project milestones + per-project counts. Call this for "how is everything going?" |
| `list_project_sessions` | sync | Enumerate the agent's resumable conversation sessions for one project. Use the returned `id` with `dispatch(session_id=...)` to switch threads. |
| `add_project` | sync | Register a new project. Validates agent name. Auto-trusts codex dirs. |
| `update_project` | sync | Change an existing project's agent, description, tags, permission_mode, fallback, or `session_id` pin. |
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

| Agent | Non-interactive invocation | `bypass` mode flag | `auto` mode flag |
|---|---|---|---|
| `claude` | `claude -p "<prompt>" --continue` | `--dangerously-skip-permissions` | `--enable-auto-mode --permission-mode auto` |
| `codex` | `codex exec "<prompt>"` | `--dangerously-bypass-approvals-and-sandbox` | — |
| `gemini` | `gemini -p "<prompt>"` | `--yolo` | — |
| `droid` | `droid exec "<prompt>"` | `--skip-permissions-unsafe` | — |
| `opencode` | `opencode run "<prompt>" --continue` | `--dangerously-skip-permissions` | — |

Agent names are validated at registration time — typos like `cursor-agent` are caught immediately, not at dispatch time.

### Switching agents mid-project

You can change a project's registered agent any time — useful when a given codebase turns out to pair better with a different CLI:

```
update_project(name="my-app", agent="codex")
```

`update_project` also accepts `description`, `tags`, `permission_mode`, and `fallback` — omitted fields stay untouched. Switching to `codex` auto-adds the project dir to `~/.codex/config.toml` trust list.

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

### Permission modes

Most coding agents ask "is this OK?" before editing files, running commands, or installing packages. That's fine when a human is at the terminal — but anywhere central-mcp runs, there's no TTY to answer approval prompts, so the work can **hang forever waiting for a reply that never comes**. Every agent instance central-mcp spawns (orchestrator pane or project-level dispatch) runs in one of three **permission modes**:

| Mode | What auto-approves | When to use |
|---|---|---|
| `bypass` | Everything. central-mcp emits each agent's own permission-skip flag (see mapping below). | Default. Fastest. No prompt-injection defense. Available on every supported agent. |
| `auto` | Cwd-local file work, declared deps, read-only HTTP, pushes to branches Claude created. Everything else goes through a background **classifier** that blocks `curl \| bash`, prod deploys, force-push, cloud bulk deletes, etc. | Sensitive repos where prompt-injection resistance matters. **Only supported by `claude`** today (and only with Team/Enterprise/API plan + **Sonnet 4.6 or Opus 4.6** — no Haiku, no 4.7, no third-party providers). central-mcp refuses `auto` for any non-claude agent or fallback chain. |
| `restricted` | Nothing. Any tool call that would normally prompt a human refuses and the agent surfaces the error. | Hardening for read-only tasks — Q&A, explain-code, reporting. Writes/builds/shell will fail. Available on every agent. |

Each vendor brands their permission-skip differently — central-mcp's `bypass`/`auto` are unified names that map to the right vendor flag per agent:

| central-mcp mode | claude | codex | gemini | droid | opencode |
|---|---|---|---|---|---|
| `bypass` | Skip permissions<br>`--dangerously-skip-permissions` | Bypass approvals + sandbox<br>`--dangerously-bypass-approvals-and-sandbox` | YOLO<br>`--yolo` | Skip permissions (unsafe)<br>`--skip-permissions-unsafe` | Skip permissions<br>`--dangerously-skip-permissions` |
| `auto` | Auto mode<br>`--enable-auto-mode --permission-mode auto` | — | — | — | — |
| `restricted` | *(no flag)* | *(no flag)* | *(no flag)* | *(no flag)* | *(no flag)* |

If a vendor adds an equivalent to claude's `auto` mode later (codex sandbox-warn, gemini review-mode, etc), central-mcp will wire it into this same `auto` alias — existing config keeps working.

Modes apply at two separate layers:

#### 1. Orchestrator layer — `central-mcp run` / `central-mcp tmux` / `central-mcp up` / `central-mcp zellij`

This is the agent *you* talk to — the orchestrator pane that calls MCP tools. **Default: `bypass`.** Change it with `--permission-mode`:

```bash
central-mcp tmux   --permission-mode auto        # claude-only, classifier-reviewed
central-mcp run    --permission-mode restricted  # no auto-approval, prompts will halt
central-mcp zellij --permission-mode bypass      # explicit default
```

With orchestrator `bypass`, the orchestrator can freely read/write files inside `~/.central-mcp` without asking — so `CLAUDE.md`, scratch notes, and hub-level edits happen without friction. With `auto` (claude + Sonnet/Opus 4.6 only), a background classifier vets each action instead of a blanket skip. `auto` is ignored (no flags emitted) for non-claude orchestrators. The orchestrator mode does **not** propagate to dispatched project agents; those carry their own per-project value.

#### 2. Per-project dispatch layer — `dispatch(..., permission_mode=...)` / `registry.yaml`

This controls the agent spawned inside a specific project's cwd for one dispatch. The value is saved to `registry.yaml` on first dispatch (default: `"bypass"`) and reused for every subsequent dispatch to that project. Flip it anytime:

```
dispatch(name="my-app", prompt="…", permission_mode="bypass")      # auto-approve, save
dispatch(name="my-app", prompt="…", permission_mode="auto")        # claude-only, classifier
dispatch(name="my-app", prompt="…", permission_mode="restricted")  # no skip, no classifier
update_project(name="my-app", permission_mode="auto")              # flip without dispatching
```

`"auto"` is rejected with an explicit error if the project's agent chain includes anything other than `claude` — central-mcp never silently downgrades auto to bypass for a fallback. With `"restricted"`, read-only dispatches still work (answering questions, reading files, explaining code); anything that would prompt (editing, shell, deps) times out — retry with `bypass`/`auto`, or open a regular terminal in the project's cwd for interactive approval.

> ### ⚠️ `bypass` is powerful — and at your own risk
>
> In `bypass` mode (at either layer), the agent may edit files, run shell commands, install packages, call network services, and push code **without confirming with you first**. That is what makes non-stop orchestration possible, but it also means a misguided prompt, prompt injection from a malicious source, or an agent hallucination can cause real damage — dropped tables, force-pushed branches, deleted files, leaked credentials, unintended API spend, etc.
>
> `auto` mode is a middle ground — still headless, but a classifier blocks a standard set of destructive patterns (see the [Claude Code permission-modes docs](https://code.claude.com/docs/permission-modes) for the default policy). It reduces prompt-injection risk but does not eliminate it. `restricted` is safest but only useful for agents that don't need to write.
>
> Typical reasoning:
> - **Orchestrator mode** controls what the *hub-level* agent can do in `~/.central-mcp` and when calling MCP tools. Lower risk in practice because the hub dir has no production code, but still read/write.
> - **Per-project mode** controls what each *project-level* agent can do inside that project's cwd. This is the higher-risk layer — it can rewrite your source, run your build, push branches.
>
> **Switch away from `bypass` (to `auto` for claude, or `restricted`) if any of these apply**:
> - The project (or `~/.central-mcp`) holds sensitive code, secrets, or production data you can't lose.
> - No safety-net commit/push is in place.
> - You didn't read the prompt carefully or you're delegating work from untrusted sources.
> - You want to review every command the agent is about to run.
>
> **Disclaimer**: central-mcp is a routing layer and does not supervise what the agents do. You are responsible for the scope, targets, and consequences of every dispatch you run in `bypass` (or `auto`) mode at either layer. The authors and contributors of central-mcp are not liable for any damage, data loss, security breach, cost, or other harm that results from the selected mode. Use snapshots (git commits, backups, branch protection), least-privilege credentials, and offline/sandboxed environments where possible.

If a project deals with sensitive code and you're not comfortable granting blanket `bypass`, switch to `auto` (claude + Sonnet/Opus 4.6) or keep `restricted` and stick to read-only dispatches.

### Session handling (conversation continuity)

By default, every dispatch resumes the agent's most-recently-modified conversation in the project's cwd — `claude --continue`, `codex exec resume --last`, `gemini --resume latest`, `opencode --continue`. **Droid is the exception**: its headless exec has no "resume latest", so a droid dispatch without an explicit session id always starts a fresh thread.

When the user wants to switch to a specific session (or recover from ambient drift — e.g., an interactive session in the same cwd made the "latest" move), `dispatch(session_id=...)` is a **one-shot override**:

```
list_project_sessions("my-app")
  → [{id: "a1b2...", title: "auth refactor", modified: "..."}, ...]

dispatch("my-app", "continue from there", session_id="a1b2...")
  # → claude -p "..." -r a1b2...
```

After that dispatch, the resumed session is now the most-recently-modified — so the **next** default `dispatch("my-app", "...")` picks it up via `--continue` automatically. You only restate the id when you want to switch threads.

For drift-proof behavior (or for droid, which needs a persistent pin to keep continuity), pin the session:

```
update_project("my-app", session_id="a1b2...")
# All future dispatches carry -r/-s <id> regardless of ambient state.

update_project("my-app", session_id="")
# Empty string clears the pin.
```

Resolution precedence when dispatching: explicit `session_id` arg > project's saved `session_id` > agent's resume-latest flag.

| Agent | Specific-session flag | Source of session list |
|---|---|---|
| `claude` | `-r <uuid>` | `~/.claude/projects/<slug(cwd)>/*.jsonl` |
| `codex` | `resume <uuid>` | `~/.codex/sessions/**/*.jsonl` filtered by `cwd` in session_meta |
| `gemini` | `--resume <index>` | `gemini --list-sessions` (numeric indexes, not UUIDs) |
| `droid` | `-s <uuid>` | `~/.factory/sessions/<slug(cwd)>/*.jsonl` |
| `opencode` | `-s <uuid>` | `opencode session list` (global, not cwd-scoped) |

### Dispatch history (per project)

Every dispatch streams its `start` / `output` / `complete` events into `~/.central-mcp/logs/<project>/dispatch.jsonl` (append-only). `dispatch_history` reads the terminal events back, merged with their matching `start`:

```
dispatch_history(name="my-app")          # last 10 dispatches for my-app
dispatch_history(name="my-app", n=50)    # last 50
```

For a cross-project view, use `orchestration_history` (below).

### Orchestration history (portfolio view)

Asks "how is everything going?" in one shot. Reads the global timeline at `~/.central-mcp/timeline.jsonl` (also append-only) plus the server's in-memory in-flight table:

```
orchestration_history()                  # in-flight + last 20 milestones across all projects
orchestration_history(n=100)             # wider slice of history
orchestration_history(window_minutes=60) # only count activity in the last hour
```

The response bundles: `in_flight` (running now), `recent` (newest milestones), `per_project` (dispatched/succeeded/failed/cancelled counts, last timestamp), and a registry snapshot. The orchestrator uses this to write a multi-project summary in one pass.

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
central-mcp                        # no-arg → launch orchestrator (same as `run`)
central-mcp run [--agent X] [--pick] [--permission-mode {bypass,auto,restricted}]
                                   # launch orchestrator (default: bypass; auto is claude-only)
central-mcp serve                  # run MCP server on stdio (used by MCP clients)
central-mcp install CLIENT         # register with claude | codex | gemini | opencode
central-mcp alias [NAME]           # short-name symlink (default: cmcp)
central-mcp unalias [NAME]
central-mcp init [PATH]            # scaffold registry.yaml (default: ~/.central-mcp)
central-mcp add NAME PATH [--agent claude|codex|gemini|droid|opencode]
central-mcp remove NAME
central-mcp list                   # one-line registry dump
central-mcp brief                  # orchestrator-ready markdown snapshot
central-mcp up [--no-orchestrator] [--permission-mode {bypass,auto,restricted}] [--max-panes N]
                                   # optional tmux observation layer
central-mcp tmux [same flags as up]
                                   # create session if missing, then attach via tmux
central-mcp zellij [same flags as up]
                                   # same, but via zellij (generates a KDL layout)
central-mcp down                   # kill observation session
central-mcp watch NAME [--from-start]
                                   # stream one project's dispatch events
central-mcp upgrade [--check]      # self-update from PyPI (uv → pip fallback)
```

## Optional observation layer

### Why it's *optional*

- **Orchestrator is the primary surface.** `dispatch` / `check_dispatch` / `orchestration_history` return structured summaries; the orchestrator turns those into natural-language status — no scrolling stdout required.
- **Work should be possible from anywhere.** central-mcp is designed so a phone/tablet over SSH is enough to keep moving. The hub can't require a multi-pane desktop to function.
- **Turn observation on only when the live view actually helps** — debugging a stuck agent, tailing a long migration, or screen-sharing the fleet. For normal operation it adds noise, not signal.

### Backends

Two multiplexer backends are supported:

- **tmux** — `central-mcp tmux` (creates the session if missing, then attaches)
- **zellij** — `central-mcp zellij` (generates a KDL layout, launches a zellij session named `central` or attaches to an existing one)

Both produce the same logical layout (hub tab + overflow tabs, project panes running `central-mcp watch <project>`). Pick the one you already have installed; you can use both from different terminals as long as they don't share a session name at the same time.

`central-mcp up` creates a tmux session `central` with:

- **Pane 0 — orchestrator** (Claude Code / Codex / Gemini / opencode), launched in `~/.central-mcp` so it picks up the hub's `CLAUDE.md` / `AGENTS.md`.
- **Panes 1…N — one per registered project**, each streaming that project's dispatch activity live via `central-mcp watch <project>`. Every dispatch's prompt, output, exit code, and duration scrolls past in real time.

Windows are named `cmcp-<N>` with the first window picking up a `-hub` suffix (`cmcp-1-hub`) when it holds the orchestrator — so you can tell at a glance which window to jump to. Cycle panes with `Ctrl+b n` / `Ctrl+b <digit>`. When the registry has more projects than fit in one window, extra windows (`cmcp-2`, `cmcp-3`, …) are added automatically. `--max-panes N` sets a per-window cap; without it, central-mcp reads the current terminal's size and picks how many panes fit above the readability floor (~70 cols × 15 rows per pane — tuned so a 13–15" laptop full-screen lands on 2 column slices).

**Orchestrator layout**: the first window puts the orchestrator pane in a full-height left column sized to match one project column. So `orch + 1 project` reproduces a 50/50 split, `orch + 3 projects` yields four equal columns (orch + 3 projects in a single row), and `orch + 9 projects` gives orch a 1/6 column with 2 × 5 project grid on the right.

```bash
central-mcp tmux                   # one-shot: create the session if missing, then attach
central-mcp tmux --permission-mode auto        # claude-only; classifier-reviewed orchestrator
central-mcp tmux --permission-mode restricted  # orchestrator surfaces approval prompts
central-mcp tmux --no-orchestrator # watch panes only (no orchestrator)
central-mcp tmux --max-panes 6
central-mcp up                     # create the session but don't attach (scripted flows)
central-mcp down                   # tear the session back down
```

The hub window (`cmcp-1-hub`) uses tmux's `main-vertical` layout: the orchestrator pane sits on the left taking two cells' worth of space, and project panes stack on the right. So the hub holds `panes_per_window − 1` panes (default 3 — orchestrator + 2 projects), and overflow windows get the full `panes_per_window` projects each. Every pane carries its role name on its top border, and the orchestrator border is highlighted in bold yellow so you can spot it at a glance.

Kill with `central-mcp down` — the MCP dispatch path never depends on this layer, so tearing it down doesn't affect in-flight dispatches. The `watch` command is a read-only tail of `~/.central-mcp/logs/<project>/dispatch.jsonl`; you can also run it standalone in any terminal.

#### Upgrading while an observation session is attached

Only matters if you use the observation layer. If you don't (dispatch-only workflow), skip this subsection.

When you `central-mcp upgrade` (or `pip install -U central-mcp`) with a `cmcp up` session already running, the panes keep holding the **previous version's** orchestrator CLI and `central-mcp watch` child processes. Those processes don't pick up binary changes mid-flight — added event types, updated argv flags, new instruction files in `~/.central-mcp/`, etc, won't reach them until they restart. On attach you may see stale agent output or zellij's "Exit: 0 — Enter to re-run" message on a watch pane whose old child has died.

**0.6.8+**: there's nothing to worry about. Every `cmcp tmux` / `cmcp zellij` invocation unconditionally tears down the prior observation session (if any) and rebuilds at the current terminal's size before attaching. You always end up with fresh panes carrying the newly-installed binary, laid out for the terminal you're actually in. `central-mcp upgrade` additionally tears down the observation session before replacing the binary, so even the upgrade-while-attached case is handled.

Trade-off: if two terminals are simultaneously attached to the same session and one runs `cmcp tmux`, the other disconnects. In exchange, you never have to think about "stale session vs new binary" ever again.

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
uv run --group dev pytest             # 141 unit tests (fast, no real CLIs)
uv run --group dev pytest -m live     # 20 live tests — shell out to real agent binaries
                                      # (claude/codex/gemini/droid); each case skips
                                      # cleanly if that binary isn't on PATH
```

## License

MIT.
