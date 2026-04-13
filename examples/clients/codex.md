# Registering central-mcp with Codex CLI

Add to `~/.codex/config.toml`:

## Recommended: `uv run` (local checkout)

```toml
[mcp_servers.central]
command = "uv"
args = [
    "run",
    "--directory", "/Users/andy/Projects/project-central",
    "python", "-m", "central_mcp",
]

[mcp_servers.central.env]
CENTRAL_MCP_REGISTRY = "/Users/andy/Projects/project-central/registry.yaml"
```

## Future: `uvx` (once published to PyPI)

```toml
[mcp_servers.central]
command = "uvx"
args = ["central-mcp"]
```

## Why this is the point

The same MCP server binary is consumed by Claude Code and Codex with identical
tool names and semantics. This is the core demonstration of orchestrator-
agnosticism: one server, any client.
