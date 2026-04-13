# Registering central-mcp with Claude Code

## Recommended: `uv run` (local checkout)

`uv run` resolves the virtualenv and installs dependencies on first launch —
no manual `pip install` step, and no hardcoded `.venv` path.

```bash
claude mcp add central -- \
    uv run --directory /Users/andy/Projects/project-central python -m central_mcp
```

With an explicit registry path:

```bash
claude mcp add \
    -e CENTRAL_MCP_REGISTRY=/Users/andy/Projects/project-central/registry.yaml \
    central -- \
    uv run --directory /Users/andy/Projects/project-central python -m central_mcp
```

Add `-s project` to scope the server to the current project rather than user-global.

## Future: `uvx` (once published to PyPI)

```bash
claude mcp add central -- uvx central-mcp
```

Zero install — `uvx` downloads and runs the package in an ephemeral environment.

## Verify

Start a Claude Code session and run `/mcp` — you should see `central` listed.
The exposed tools are `list_projects`, `project_status`, `dispatch_query`, `fetch_logs`.
