---
name: central-mcp
description: "Orchestrate coding agents across every registered project via central-mcp's MCP tools."
version: 1.0.0
author: central-mcp
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Orchestration, MCP, Dispatch, Multi-Project, Coding-Agent, Portfolio]
    related_skills: [claude-code, codex, opencode]
---

# central-mcp — Hermes Orchestration Guide

[central-mcp](https://central-mcp.org) is a dispatch hub across the user's registered projects. Each project is bound to a coding-agent CLI (claude / codex / gemini / opencode / droid / hermes). If `cmcp install hermes` has been run, its MCP tools are already registered in your `config.yaml` as the `central` server — you can call them natively.

Prefer these tools over raw `terminal` commands whenever the work targets a **registered project**: dispatches get logging, history, token accounting, quota-aware fallback, and observation surfaces for free. Use `terminal` for ad-hoc work outside the registry.

## Core loop

1. **`list_projects`** — see the portfolio (name, agent, path, tags). Pass `workspace="__all__"` for every workspace.
2. **`dispatch(name, prompt)`** — run the project's agent non-interactively in its cwd. **Non-blocking**: returns a `dispatch_id` in <100 ms while the agent works in the background.
3. **`check_dispatch(dispatch_id)`** — poll. `{status: "running", elapsed_sec}` while alive; the full result (`output`, `tokens`, `duration_sec`) once finished.
4. **`cancel_dispatch(dispatch_id)`** — abort a runaway dispatch.

```
dispatch(name="my-app", prompt="Run the test suite and fix any failures")
→ {dispatch_id: "a1b2c3d4"}
check_dispatch(dispatch_id="a1b2c3d4")
→ {status: "running", elapsed_sec: 42.0}   # later: full result
```

Coding dispatches routinely take 1–15 minutes. Do **not** busy-wait: check once ~every 3 s only if the user is waiting on the answer; otherwise report the dispatch_id, move on, and re-check on your next turn, heartbeat, or cron tick. Every central-mcp tool response also piggybacks completions that finished since your last call, so any later tool use surfaces finished work automatically.

## Fan-out

`dispatch(name="@workspace-name", prompt=...)` sends one prompt to **every project in that workspace** at once and returns one dispatch_id per project. Good for portfolio-wide chores ("update CI config", "audit dependencies").

## Portfolio awareness

- **`orchestration_history`** — one call returns in-flight dispatches, recent milestones (with prompt/output previews), and per-project success/failure stats. Use it whenever the user asks "how is everything going?".
- **`token_usage`** — subscription quota %, per-agent totals, per-project breakdown, plus a pre-rendered `summary_markdown` you can forward verbatim.
- **`dispatch_history(name)`** — last N dispatches for one project.

## Hermes-specific leverage

You have capabilities the terminal-bound orchestrators lack — use them:

- **Cron digests.** A daily cron job that calls `orchestration_history` + `token_usage` and posts the summary to the user's Telegram / Discord makes central-mcp's portfolio state ambient. This is the single highest-value integration.
- **Completion pings.** After starting a long dispatch from a chat conversation, re-check it on your next heartbeat and message the user when it finishes — they never have to ask.
- **Bidirectional.** Projects registered with `agent: hermes` dispatch *to* you; that path is not your concern here. This skill is about you as the *caller*.

## Cautions

- Dispatches run with permissions bypassed inside the project's cwd. Don't dispatch prompts you wouldn't run unattended; keep destructive operations (`git push --force`, deletions) out of dispatch prompts unless the user explicitly asked.
- One dispatch per project at a time is the norm; check `list_dispatches` before piling on.
- If a dispatch fails, `check_dispatch` carries `stderr` / `error` — read them before retrying, and consider `dispatch(..., agent="<other>")` to route around a quota-exhausted agent.
