# Registering central-mcp with Cursor

## Recommended: `central-mcp install cursor`

```bash
central-mcp install cursor
```

This patches `~/.cursor/mcp.json` to add the `central` server entry. Idempotent — rerunning is a no-op if already registered.

Preview without writing:

```bash
central-mcp install cursor --dry-run
```

## Manual

Create or edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "central": {
      "command": "central-mcp",
      "args": ["serve"]
    }
  }
}
```

## Dispatch

Cursor projects use `cursor-agent -p "<prompt>" --resume` for non-interactive dispatch. The `--resume` flag automatically picks up the last session in the project's working directory.

## Verify

Open Cursor and check MCP server status — `central` should be connected with 8 tools available.
