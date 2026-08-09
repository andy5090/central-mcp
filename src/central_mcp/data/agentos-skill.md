---
name: central-mcp
description: "Orchestrate coding agents across every registered project via central-mcp's MCP tools, and deliver portfolio reports to chat."
version: 2.0.0
author: central-mcp
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Orchestration, MCP, Dispatch, Multi-Project, Coding-Agent, Portfolio]
    related_skills: [claude-code, codex, opencode]
---

# central-mcp — agentOS Orchestration Guide

[central-mcp](https://central-mcp.org) is the **portfolio PM** for someone running many agent-driven projects at once. Each registered project is bound to a coding-agent CLI (claude / codex / gemini / opencode / droid / hermes / openclaw / gjc). If `cmcp install <you>` has been run, its MCP tools are registered as the `central` server and you can call them natively.

Prefer these tools over raw shell commands whenever the work targets a **registered project**: dispatches get logging, history, token accounting, quota-aware fallback, and observation surfaces for free. Use your shell for ad-hoc work outside the registry.

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

## Answering "how is X doing?"

| The user asks | Call |
|---|---|
| "what's the state of X?", or they return to X after a while | `project_pulse(X)` |
| "what happened in X" deeper than a few dispatches | `dispatch_history(X, n=…)` |
| "overall status?", "how is everything going?" | `orchestration_history()` |
| "daily/weekly recap", "summarize the portfolio" | `portfolio_digest()` — forward `digest_markdown` verbatim |
| "how many tokens?", "budget left?" | `token_usage()` — forward `summary_markdown` verbatim |

**`project_pulse` is the one that sees everything.** The history tools only know about work that went *through* central-mcp; a pulse reads the repository itself, so direct commits, interactive agent sessions, and manual edits show up too. After any absence, that is usually where the interesting work is. Synthesize it into a short narrative — *what happened / where it stands / what's next* — rather than reciting fields.

Never report a dispatch in `dispatches.stale` as live work: those rows sat in `running` for hours because a crashed or restarted server never wrote their terminal state. They are unfinished, not in progress.

## Your leverage as a resident agent

You have what terminal-bound orchestrators lack: **cron and a chat gateway**. That makes you the delivery rail for central-mcp's push reporting — the PM that finds the user instead of waiting to be visited. Set these up proactively when the user asks for "daily updates", "keep me posted", or anything similar.

### Recipe 1 — daily digest (cron)

Create a cron job (daily, e.g. 08:00 local) whose task is:

1. Call **`portfolio_digest()`** (add `since_hours=168` for a weekly variant, or `workspace="__all__"` to cross workspaces).
2. Send `digest_markdown` to the user's primary chat channel **verbatim — do not re-summarize, reorder, or trim it**. The format is fixed server-side precisely so every day's report looks the same; your paraphrase would undo that.
3. Only when `warnings` is non-empty, you may prepend one short line of your own (e.g. "2 warnings need a look today").

The digest is pulse-powered: it counts work that never went through central-mcp, flags failed dispatches, dispatches stuck in `running` for hours, and quiet projects with uncommitted changes sitting in them.

### Recipe 2 — failure watch (cursor, no re-alerts)

On a frequent tick (each heartbeat, or a 15-minute cron):

1. Call **`list_dispatches(status="failed", since=<watermark>)`** — `failed` covers `error`, `timeout`, and `complete`-with-`ok=false`; cancelled is deliberate and excluded.
2. If rows come back: alert the user (project, agent, `dispatch_id`; fetch `check_dispatch(id)` for `stderr`/`error` details if the user will want them).
3. Advance your watermark to the **max `finished_at`** among the rows you just saw, and persist it in your own memory. The filter is strictly-greater-than, so an unchanged watermark never re-alerts the same failure.
4. First run (no watermark yet): call without `since`, alert on nothing, and just record the max `finished_at` as your starting point — alerting on stale history helps no one.

The watermark is **yours** to keep: central-mcp is stateless between requests and does not track subscribers.

### Also

- **Completion pings.** After starting a long dispatch from a chat conversation, re-check it on your next heartbeat and message the user when it finishes — they never have to ask.
- **Bidirectional.** A project registered with your own agent name dispatches *to* you; that path is not your concern here. This skill is about you as the *caller*.

## Cautions

- Dispatches run with permissions bypassed inside the project's cwd. Don't dispatch prompts you wouldn't run unattended; keep destructive operations (`git push --force`, deletions) out of dispatch prompts unless the user explicitly asked.
- One dispatch per project at a time is the norm; check `list_dispatches` before piling on.
- If a dispatch fails, `check_dispatch` carries `stderr` / `error` — read them before retrying, and consider `dispatch(..., agent="<other>")` to route around a quota-exhausted agent.
