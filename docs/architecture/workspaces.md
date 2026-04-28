# Workspaces

A workspace is a named subset of registered projects. Use them to:

- Keep client engagements separated (`client-a`, `client-b`, …) so a `list_projects` from inside one engagement doesn't surface the other's projects.
- Fan out a single prompt to every project in a logical group at once (`dispatch("@frontend", "tighten the README")`).
- Run multiple `cmcp` instances in different terminals at the same time, each scoped to a different workspace.
- Slice token usage and quota views by group rather than by single project.

Every install starts with one workspace called `default` that holds every project you've registered.

---

## Quick example

```bash
# create a workspace and add some projects to it
cmcp workspace new client-a
cmcp workspace add my-app    --workspace client-a
cmcp workspace add api-server --workspace client-a

# switch the saved default to client-a (affects new shells)
cmcp workspace use client-a

# inside an orchestrator session scoped to client-a, this fan-out
# dispatches to every project in the workspace at once
"Send all my projects the same prompt: tighten the README."
```

---

## Where the data lives

| File | Role |
|---|---|
| `~/.central-mcp/registry.yaml` | `projects:` list + `workspaces:` map (`{name: [project, …]}`). |
| `~/.central-mcp/config.toml` | `[user].current_workspace` — your saved default workspace. |

A project may appear in multiple workspaces; central-mcp doesn't enforce mutual exclusion. Projects you never explicitly assign live in `default`.

---

## CLI

All workspace commands are under `cmcp workspace`:

```bash
cmcp workspace list              # show every workspace + project count
cmcp workspace current           # print the active workspace name
cmcp workspace new <name>        # create an empty workspace
cmcp workspace use [<name>]      # switch active (interactive picker if name omitted)
cmcp workspace add <project> --workspace <name>      # assign a project
cmcp workspace remove <project> --workspace <name>   # unassign
```

`cmcp workspace use` with no argument opens an arrow-key picker showing every workspace with its project count and a `[current]` marker on the active one.

`cmcp workspace use <name>` writes to `config.toml` and is **persistent** — every new shell on this machine inherits it. For a one-off override (a single shell, no config write), use `cmcp run --workspace <name>` or set `CMCP_WORKSPACE` in that shell's env (see *Concurrent workspaces* below).

---

## Running orchestrators against a workspace

### Default behavior (single workspace, saved)

```bash
cmcp                # uses config.toml [user].current_workspace
```

The orchestrator sees only that workspace's projects when it calls `list_projects()` with no arguments. Dispatch fan-out (`@workspace`) targets the same scope.

### One-off override (this terminal only)

```bash
cmcp run --workspace client-a
```

This sets `CMCP_WORKSPACE=client-a` in the launched orchestrator's environment. The MCP server child inherits it via stdio. The saved default in `config.toml` is **not** changed, so opening another terminal and running `cmcp` will still use whatever the saved default is.

### Concurrent workspaces (multiple terminals)

```bash
# terminal 1 — Claude Code on client-a
cmcp run --workspace client-a

# terminal 2 — Codex on client-b at the same time
cmcp run --workspace client-b
```

Each instance is fully isolated for `list_projects`, dispatch fan-out, and `token_usage(workspace=…)`. They share `tokens.db`, `dispatches.db`, and the `registry.yaml` (workspace-scoped reads, all multi-process safe).

You can also `export CMCP_WORKSPACE=client-a` once per shell instead of passing `--workspace` to every command.

### Resolution order for `current_workspace()`

1. `CMCP_WORKSPACE` env var (per-process)
2. `config.toml [user].current_workspace` (saved default)
3. Literal `default`

---

## MCP tool calls — what changes inside the orchestrator

When the orchestrator session is scoped to a workspace, every tool that takes `workspace` as a parameter defaults to the active one:

| Tool | Default behavior |
|---|---|
| `list_projects()` | Returns projects in the active workspace. |
| `list_projects(workspace="__all__")` | Every project across every workspace. |
| `orchestration_history()` | Filtered to the active workspace. |
| `token_usage()` | Aggregated across the active workspace. |
| `dispatch("@workspace", prompt)` | Fan-out to every project in the *named* workspace (not necessarily the active one — `@<name>` is explicit). |
| `dispatch("project-name", prompt)` | Single project; not affected by workspace scope. |

`@workspace` resolution: if a name matches both a project and a workspace, the project wins. Use `@<name>` to force workspace resolution.

---

## Observation panes

`cmcp up`, `cmcp tmux`, and `cmcp zellij` honor the workspace too:

```bash
cmcp tmux --workspace client-a    # session named cmcp-client-a, panes only for client-a's projects
cmcp tmux --all                   # one cmcp-<workspace> session per workspace
cmcp tmux switch <workspace>      # detach from current, attach to another workspace's session
```

When `--workspace` is explicit on `cmcp tmux/zellij`, the orchestrator pane gets `CMCP_WORKSPACE=<name>` injected into its launch command — so the orchestrator sees the right scope independent of the shell that ran `cmcp tmux`.

cmux works the same way at the layout level: the agent-driven setup (see [Observation](../observation.md)) lays out one pane per project that the active workspace contains.

---

## Token usage by workspace

```python
# inside the orchestrator
token_usage(period="week", workspace="client-a")
# → breakdown limited to client-a's projects
# → quota snapshot is global (subscriptions are per-account, not per-workspace)
```

The `summary_markdown` field in the response is rendered with the same workspace scope.

---

## What workspaces are *not*

- **Not isolated registries.** All workspaces live in the same `registry.yaml`. Removing a workspace doesn't delete its projects — they fall back to `default` ownership.
- **Not separate token / dispatch databases.** `tokens.db` and `dispatches.db` are global; workspace filtering happens at read time via the registry.
- **Not access-controlled.** Anyone with shell access to your `~/.central-mcp/` sees every workspace. Use OS-level permissions if you need stronger separation.
- **Not auto-derived from project paths.** Membership is explicit — `cmcp workspace add` is the only way a project joins a workspace.
