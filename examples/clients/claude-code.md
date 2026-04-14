# Registering central-mcp with Claude Code

## Recommended: `central-mcp install claude`

Let the CLI do it for you. After `uv tool install --editable .` (or `uv tool install central-mcp` post-publish):

```bash
central-mcp install claude
```

This runs `claude mcp add central -- central-mcp serve` under the hood.

## Manual

```bash
claude mcp add central -- central-mcp serve
```

If `central-mcp` is not on your PATH (e.g. you're running from a bare checkout without `uv tool install`), fall back to running the module through `uv run`:

```bash
claude mcp add central -- uv run --directory ~/Projects/central-mcp python -m central_mcp serve
```

## Verify

Start a Claude Code session and run `/mcp` — you should see `central` listed. The exposed tools are `list_projects`, `project_status`, `project_activity`, `dispatch_query`, `fetch_logs`, `start_project`, `add_project`, `remove_project`.
