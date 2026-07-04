---
title: central-mcp
description: central-mcp turns any MCP-capable client into a parallel control plane for Claude Code, Codex, Gemini, opencode, and Hermes Agent — fan out work across every project at once and let the hub absorb the context switching.
hide:
  - toc
---

<div class="cmcp-hero" markdown="1">

<div class="cmcp-hero-bg" aria-hidden="true">
  <span class="cmcp-lane" style="--speed: 6.0s; --offset: 0.0s; --top: 18%;"></span>
  <span class="cmcp-lane" style="--speed: 7.5s; --offset: 0.6s; --top: 32%;"></span>
  <span class="cmcp-lane" style="--speed: 5.5s; --offset: 1.1s; --top: 62%;"></span>
  <span class="cmcp-lane" style="--speed: 8.5s; --offset: 0.3s; --top: 78%;"></span>
</div>

<p class="cmcp-hero-logo">
  <img src="/logo.png?v=0.11.0" alt="central-mcp" width="300" class="cmcp-hero-light"/>
  <img src="/logo-dark.png?v=0.11.0" alt="central-mcp" width="300" class="cmcp-hero-dark"/>
</p>

<h1 class="cmcp-hero-title">Tokenmaxxing, <span class="cmcp-hero-emph">disciplined.</span></h1>

<p class="cmcp-hero-sub">Fan out Claude Code, Codex, Gemini, opencode, and Hermes Agent across every project in parallel. central-mcp absorbs the context switching — tokens climb to <span class="cmcp-hero-counter" data-min="10" data-max="100">10×</span>, your focus stays put.</p>

[Get started](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/andy5090/central-mcp){ .md-button }
[PyPI](https://pypi.org/project/central-mcp/){ .md-button }

</div>

central-mcp turns any MCP-capable client into a control plane for your portfolio of coding-agent projects. Speak naturally; the orchestrator routes each request to the right project's agent — non-blocking, with results reported back asynchronously.

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

## Live observation — cmux-friendly

Run several projects in parallel, watch them all live. central-mcp ships an observation layer with three backends: **[cmux](https://github.com/manaflow-ai/cmux)** (macOS GUI), tmux, and zellij.

cmux gets a deliberate first-class treatment: its design philosophy ("agents manage their own panes") aligns with central-mcp's stateless, log-driven model. One sentence to the orchestrator — *"set up watch panes for the current workspace"* — produces a clean grid of live `cmcp watch <project>` panes around the orchestrator pane, no config files involved.

[Observation guide →](observation.md){ .md-button }

## agentOS-friendly — Hermes integration

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) is a self-improving agentOS — built-in cron, skills curation, and multi-platform delivery (Telegram, Discord, Slack, WhatsApp). It also speaks MCP both ways: `hermes mcp add` to register external servers, `hermes mcp serve` to expose its own conversations. That makes it the most natural pairing partner central-mcp has outside the four core orchestrators.

`cmcp install hermes` writes `mcp_servers.central` into `~/.hermes/config.yaml`, and from that moment Hermes sees `dispatch` / `list_projects` / `check_dispatch` as native tools. It also drops a **central-mcp skill** into Hermes's skill library (`skills/autonomous-ai-agents/central-mcp/`) — the non-blocking dispatch loop, `@workspace` fan-out, and cron-digest patterns, so Hermes doesn't just *have* the tools, it knows how to orchestrate with them. `cmcp run --agent hermes` makes Hermes the orchestrator; `add_project --agent hermes` makes a project's dispatch target Hermes. Bidirectional in one config edit.

Compositions worth noticing:

- **Autonomous portfolio summaries from your phone.** Send Hermes one line over Telegram — *"summarize what shipped across my projects today"* — and it drives `orchestration_history` + per-project dispatches without you opening a terminal.
- **Cron-driven daily digests to Slack.** Hermes's built-in cron runs nightly, calls central-mcp's MCP tools, posts the rolled-up status to your team's channel — no extra bot to install.
- **Hermes as a project's dispatch target.** Skills curation, web search, and multi-model fallback in front of the project — useful where a one-shot CLI isn't enough.

Token usage is tracked too: the `SUBSCRIPTION QUOTA` block in the token HUD gained a `hermes [ledger]` line aggregating `~/.hermes/state.db` into hour / day / week token totals + cost.

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
- **[Observation](observation.md)** — live multi-pane view (cmux / tmux / zellij)
- **[Workspaces](architecture/workspaces.md)** — project grouping
- **[Roadmap](ROADMAP.md)** — what's planned
- **[Changelog](changelog.md)** — what shipped
