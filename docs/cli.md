# CLI reference

`central-mcp` is the full command name; `cmcp` is the short alias created by `central-mcp init`.

!!! note
    Auto-extraction of `--help` text is on the roadmap. Until then, this page is a curated overview — run `central-mcp <subcommand> --help` for the canonical, always-up-to-date text.

## Top-level

```text
central-mcp [SUBCOMMAND] [OPTIONS]
```

When invoked with no subcommand, `central-mcp` is equivalent to `central-mcp run`.

---

## Launching the orchestrator

### `central-mcp run`
Launch the configured orchestrator (claude / codex / gemini / opencode). Probes PyPI for newer releases on every launch and offers an interactive upgrade picker. Walks the fallback chain if the preferred orchestrator is over its quota threshold.

### `central-mcp serve`
Run as an MCP stdio server. This is what MCP clients invoke; you rarely call it directly.

---

## Observation layer

### `central-mcp up [--workspace NAME] [--all] [--backend tmux|zellij]`
Set up a multiplexer session with one pane per project (running `cmcp watch <project>`) and the orchestrator on the side.

### `central-mcp tmux` / `central-mcp zellij`
Backend-specific session creators. Use these when you want to skip the picker.

### `central-mcp down`
Tear down the observation session.

### `central-mcp watch <project>`
Tail a project's `dispatch.jsonl` with human-readable formatting (ANSI colors, code-block detection, sticky header).

### `central-mcp monitor`
Curses portfolio dashboard: per-agent quota bars, dispatch stats by project.

---

## Registry

### `central-mcp list [--workspace NAME]`
List registered projects.

### `central-mcp brief`
One-shot text portfolio overview (no curses).

### `central-mcp add <name> <path> [--agent AGENT] [--workspace NAME]`
Register a project.

### `central-mcp remove <name>`
Deregister a project.

### `central-mcp reorder <name>...`
Reorder the project list (affects `cmcp up` pane layout order).

---

## Workspaces

### `central-mcp workspace list`
List workspaces and their project counts.

### `central-mcp workspace current`
Print the active workspace name.

### `central-mcp workspace new <name>`
Create a new workspace.

### `central-mcp workspace use [NAME]`
Switch the active workspace. With no `NAME`, opens an arrow-key picker.

### `central-mcp workspace add <project> <workspace>`
Assign a project to a workspace.

### `central-mcp workspace remove <project> <workspace>`
Unassign.

---

## MCP client setup

### `central-mcp install <client>`
Register central-mcp as an MCP server with a client. Choices: `claude`, `codex`, `gemini`, `opencode`, `all`.

### `central-mcp alias [name]`
Print or create the `cmcp` short alias.

### `central-mcp unalias`
Remove the alias.

---

## Maintenance

### `central-mcp init [--force]`
One-time setup: scaffold `~/.central-mcp/`, create the `cmcp` alias, register with detected MCP clients.

### `central-mcp upgrade`
Upgrade central-mcp to the latest PyPI release.
