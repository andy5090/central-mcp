---
description: Install central-mcp, launch an orchestrator, and dispatch your first parallel agent task in three minutes — natural-language flow from project registration to fan-out.
---

# Quickstart

Three minutes from "I just heard of central-mcp" to "I just dispatched work to three projects in parallel."

## 1. Install

```bash
curl -fsSL https://central-mcp.org/install.sh | sh
```

The installer:

1. Bootstraps [`uv`](https://docs.astral.sh/uv/) if missing.
2. Runs `uv tool install central-mcp` — pulls the latest from PyPI.
3. Runs `central-mcp init` — scaffolds `~/.central-mcp/registry.yaml` and creates the `cmcp` short alias.

??? info "Manual install (without the curl script)"
    ```bash
    # 1. Install uv (skip if already present)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # 2. Install central-mcp
    uv tool install central-mcp

    # 3. One-time setup
    central-mcp init
    ```

    `pip install central-mcp` also works if you prefer pip over uv.

## 2. Launch the orchestrator

```bash
cmcp
```

This picks your preferred orchestrator (claude / codex / gemini / opencode), launches it, and exposes central-mcp's MCP tools to it. Everything from here happens in natural language inside that session.

## 3. Register a project (just ask)

```text
Add ~/Projects/my-app to the hub. Use claude as its agent.
```

The orchestrator unwraps that into `add_project(name="my-app", path="...", agent="claude")` and confirms back. Repeat for any other projects. To see what's registered:

```text
List my projects.
```

??? info "Prefer the CLI?"
    Same operations from a shell prompt:

    ```bash
    cmcp add my-app ~/Projects/my-app --agent claude
    cmcp list
    ```

## 4. Send work

Still in the orchestrator session:

> *"Ask my-app to add a dark mode toggle in settings."*

The orchestrator:

1. Parses out the project name (`my-app`).
2. Calls `dispatch("my-app", "add a dark mode toggle in settings")` — returns immediately with a `dispatch_id`.
3. Reports the result asynchronously when the agent finishes (3 channels: piggyback on the next tool call, background poll, or your "any updates?" prompt).

You stay in conversation the whole time.

## 5. Optional: live observation

```bash
cmcp up
```

Picks tmux or zellij interactively, lays out one pane per project running `cmcp watch <project>`, and gives you the orchestrator on the side.

## What's next

- [CLI reference](cli.md) — every subcommand.
- [MCP tools](mcp-tools.md) — the API the orchestrator actually calls.
- [Workspaces](architecture/workspaces.md) — group projects, dispatch to a whole group at once.
