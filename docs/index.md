---
title: central-mcp
description: central-mcp is the portfolio PM for a person running many agent-driven projects at once — dispatch across Claude Code, Codex, Gemini, opencode, Hermes Agent, and gajae-code, get pulse briefings when you return to a project, and a daily digest that finds you.
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

<h1 class="cmcp-hero-title">All lines run through <span class="cmcp-hero-emph">central.</span></h1>

<p class="cmcp-hero-sub">Fan out Claude Code, Codex, Gemini, opencode, Hermes Agent, and gajae-code across every project in parallel — and at the center stands your Ultra PM: it always knows what happened, where things stand, and what's next. Every token goes into the work, none into remembering where you left off.</p>

[Get started](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/andy5090/central-mcp){ .md-button }
[PyPI](https://pypi.org/project/central-mcp/){ .md-button }

</div>

central-mcp is the **portfolio PM** for a person running many agent-driven projects at once. Speak naturally from any MCP-capable client; the orchestrator routes each request to the right project's agent — non-blocking, with results reported back asynchronously — and briefs you on any project's real state the moment you return to it.

---

## Why

Agents made it cheap to *run* four, eight, fifteen projects at once. They did nothing about *keeping track* of them. Every context switch charges a re-orientation tax — *what happened here while I was away? What state is it in? What was I about to do next?* — and nobody is playing PM.

central-mcp is that PM:

- **Dispatch** — send work to any project's agent, in parallel, and keep talking while it runs
- **Pulse** — return to a project and get "what happened / where it stands / what's next" computed from the repository itself, so work that never went through the hub (direct commits, interactive sessions) counts too
- **Digest** — a fixed-format daily/weekly portfolio report, deliverable to chat by a resident agent or a plain crontab
- **Observe** — live panes on the dispatches you're actively following
- **Orchestrate from anywhere** — any MCP-capable client can be the front end; never locked to one vendor

Every dispatch is a fresh subprocess in the project's cwd (e.g. `claude -p "..." --continue`). No long-lived processes, no screen scraping, no tmux dependency on the critical path.

## How you meet it — three tiers

central-mcp is a layer, not a place. A dedicated orchestrator you must remember to visit gets forgotten, so the surfaces are ranked by how they reach you:

1. **Ambient (the main way in).** `cmcp install claude` once, and every session of your daily CLI carries `dispatch`, `project_pulse`, and the rest alongside its normal tools. Open a project, ask *"where does this stand?"*, and the briefing happens in place.
2. **Reach.** The [Hermes bridge](#agentos-friendly-hermes-integration) sends the daily digest and failure alerts to Telegram/Discord — the one channel that finds *you* when no terminal is open.
3. **Focus.** `cmcp tui` (experimental), for the sessions whose main job *is* orchestration — fan out, watch it land, supervise.

## Design principles

1. **Coding agent-agnostic.** MCP tools are the canonical surface. Any MCP-capable client can be the orchestrator; any supported coding agent CLI can be the dispatch target.
2. **Non-blocking dispatch.** `dispatch` returns a `dispatch_id` in <100ms. Results arrive asynchronously. The conversation never freezes.
3. **Dispatch-router preamble.** The orchestrator is instructed to be a pure router — parse the project name, call `dispatch`, move on. This minimizes LLM reasoning latency to ~1–2 seconds per turn.
4. **File-based state.** `registry.yaml` is the single source of truth.

## Live observation — cmux-friendly

A pane is a microscope, not a map: it earns its screen by showing one project's raw output closely, while the portfolio question belongs to `cmcp pulse` and the digest. So the observation grid stays focused — panes open for the projects you're actively following (most-recently-active by default, `--projects` to choose) rather than tiling everything you've ever registered. Three backends: **[cmux](https://github.com/manaflow-ai/cmux)** (macOS GUI), tmux, and zellij.

cmux gets a deliberate first-class treatment: its design philosophy ("agents manage their own panes") aligns with central-mcp's stateless, log-driven model. One sentence to the orchestrator — *"set up watch panes for the current workspace"* — produces a clean grid of live `cmcp watch <project>` panes around the orchestrator pane, no config files involved.

[Observation guide →](observation.md){ .md-button }

## agentOS-friendly — Hermes integration

[Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research) is a self-improving agentOS — built-in cron, skills curation, and multi-platform delivery (Telegram, Discord, Slack, WhatsApp). It also speaks MCP both ways: `hermes mcp add` to register external servers, `hermes mcp serve` to expose its own conversations. That makes it the most natural pairing partner central-mcp has outside the four core orchestrators.

`cmcp install hermes` writes `mcp_servers.central` into `~/.hermes/config.yaml`, and from that moment Hermes sees `dispatch` / `list_projects` / `check_dispatch` as native tools. It also drops a **central-mcp skill** into Hermes's skill library (`skills/autonomous-ai-agents/central-mcp/`) — the non-blocking dispatch loop, `@workspace` fan-out, and cron-digest patterns, so Hermes doesn't just *have* the tools, it knows how to orchestrate with them. `cmcp run --agent hermes` makes Hermes the orchestrator; `add_project --agent hermes` makes a project's dispatch target Hermes. Bidirectional in one config edit.

Compositions worth noticing:

- **The daily digest, delivered (0.17.0).** Hermes's cron calls `portfolio_digest` and forwards the fixed-format report to Telegram/Discord verbatim — active projects with commits and dispatch outcomes, warnings (failed or never-finalized dispatches, quiet projects with uncommitted work), and a quota line. The shipped skill carries the recipe.
- **Failure alerts without re-alerts (0.17.0).** `list_dispatches(status="failed", since=…)` gives Hermes a cursor: alert on what's new, advance the watermark, never ping the same failure twice — while central-mcp stays stateless.
- **Portfolio answers from your phone.** One line over Telegram — *"summarize what shipped today"* — and Hermes drives the same tools without you opening a terminal.
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
