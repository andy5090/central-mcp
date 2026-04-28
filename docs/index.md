# central-mcp

<p align="center">
  <img src="logo.png?v=0.11.0" alt="central-mcp logo" width="240"/>
</p>

**Coding agent-agnostic MCP hub for managing multiple coding agents.**

> Never stop. Run agents across every project in parallel — 10×, 100× your throughput.

central-mcp turns any MCP-capable client (Claude Code, Codex, Gemini, opencode, …) into a control plane for your portfolio of coding-agent projects. Speak naturally, and the orchestrator routes each request to the right project's agent — non-blocking, with results reported back asynchronously.

[Get started](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/andy5090/central-mcp){ .md-button }
[PyPI](https://pypi.org/project/central-mcp/){ .md-button }

---

## Why

You probably use more than one coding agent. Each has its own terminal, its own session, its own logs. Switching between them is friction, and there is no shared view of *what answered what*.

central-mcp gives you one hub:

- **Dispatch** prompts to any project's agent and get responses via MCP
- **Parallel work** — dispatch to multiple projects and keep talking while they run
- **Manage** the registry with `add_project` / `remove_project`
- **Orchestrate** from any MCP-capable client — never locked to one

Every dispatch is a fresh subprocess in the project's cwd (e.g. `claude -p "..." --continue`). No long-lived processes, no screen scraping, no tmux dependency on the critical path.

## Design principles

1. **Coding agent-agnostic.** MCP tools are the canonical surface. Any MCP-capable client can be the orchestrator; any supported coding agent CLI can be the dispatch target.
2. **Non-blocking dispatch.** `dispatch` returns a `dispatch_id` in <100ms. Results arrive asynchronously. The conversation never freezes.
3. **Dispatch-router preamble.** The orchestrator is instructed to be a pure router — parse the project name, call `dispatch`, move on. This minimizes LLM reasoning latency to ~1–2 seconds per turn.
4. **File-based state.** `registry.yaml` is the single source of truth.

## Install

```bash
curl -fsSL https://central-mcp.org/install.sh | sh
```

Bootstraps `uv` if missing, installs `central-mcp` from PyPI, and runs `central-mcp init` to set up `~/.central-mcp/`.

## Supported platforms

| Platform | Status |
| --- | --- |
| **macOS** | Primary development and test target |
| **Linux** | Expected to work; not regularly tested |
| **Windows** | Not officially tested; cmux backend is macOS-only |

## Where to next

- **[Quickstart](quickstart.md)** — install + first dispatch
- **[CLI reference](cli.md)** — every subcommand
- **[MCP tools](mcp-tools.md)** — the API surface
- **[Workspaces](architecture/workspaces.md)** — project grouping
- **[Roadmap](ROADMAP.md)** — what's planned
- **[Changelog](changelog.md)** — what shipped
