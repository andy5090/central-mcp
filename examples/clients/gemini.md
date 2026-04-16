# Registering central-mcp with Gemini CLI

## Setup

Gemini CLI supports MCP servers via its settings file. Add central-mcp to `~/.gemini/settings.json`:

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
