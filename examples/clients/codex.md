# Registering central-mcp with Codex CLI

## Recommended: `central-mcp install codex`

Let the CLI do it — idempotent, backs up `~/.codex/config.toml` before writing:

```bash
central-mcp install codex
```

Preview without writing:

```bash
central-mcp install codex --dry-run
```

## Manual

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.central]
command = "central-mcp"
args = ["serve"]
startup_timeout_sec = 15.0
```

If `central-mcp` is not on PATH, fall back to running via `uv`:

```toml
[mcp_servers.central]
command = "uv"
args = ["run", "--directory", "/Users/you/Projects/central-mcp", "python", "-m", "central_mcp", "serve"]
```

## Why this is the point

Claude Code and Codex consume the same server binary with identical tool names. This is the core demonstration of orchestrator-agnosticism: one server, any client.
