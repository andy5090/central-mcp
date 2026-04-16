# Registering central-mcp with Gemini CLI

## Recommended: `central-mcp install gemini`

```bash
central-mcp install gemini
```

Patches `~/.gemini/settings.json` to add the `central` MCP server under the top-level `mcpServers` key. Idempotent — reruns after a successful install are no-ops. The file (and `~/.gemini/` itself) is created automatically if missing.

To preview changes without writing:

```bash
central-mcp install gemini --dry-run
```

## Manual setup (equivalent)

If you prefer editing the file yourself, the entry is:

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

If `central-mcp` is not on PATH, fall back to `uv`:

```json
{
  "mcpServers": {
    "central": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/central-mcp", "python", "-m", "central_mcp", "serve"]
    }
  }
}
```

## Dispatch

Gemini projects use `gemini -p "<prompt>"` for non-interactive dispatch. Each call is stateless — no automatic session resumption.

## Verify

Start a Gemini CLI session and check for `central` MCP tools: `list_projects`, `dispatch`, `check_dispatch`, `list_dispatches`, `cancel_dispatch`, `add_project`, `remove_project`, `project_status`.
