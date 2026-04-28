# Observation mode

central-mcp dispatches are non-blocking. You ask the orchestrator to send work to three projects, get three `dispatch_id`s in <100ms, and keep talking. The agents run in the background, in their own project directories, and stream output to per-project event logs.

The observation layer is what lets you **watch all those streams at once** — one pane per project, the orchestrator on the side, everything live.

Three backends, same shape:

| Backend | Where | When to pick it |
|---|---|---|
| **[cmux](https://github.com/manaflow-ai/cmux)** | macOS GUI app | When you want a real native window manager that agents drive themselves |
| **tmux** | Any Unix terminal | When you live in tmux already |
| **zellij** | Any Unix terminal | When you prefer zellij's defaults |

---

## Why central-mcp + cmux is special

cmux is designed around a single idea: **agents manage their own panes**. Every pane it spawns gets `CMUX_WORKSPACE_ID` and `CMUX_SURFACE_ID` injected into its environment, and there's a CLI (`cmux new-split`, `cmux send-text`, `cmux tree --json`) that the agent calls to compose its own layout.

That philosophy lines up exactly with how central-mcp is built:

- **Stateless** — no daemon to coordinate; central-mcp leaves a `dispatch.jsonl` per project, the agent decides what to render where.
- **Log-driven** — `cmcp watch <project>` is just a tail of the per-project event stream, with sticky headers and color. cmux gives that a real GUI window per pane, with native font rendering, GPU-accelerated scrolling, and macOS-style Cmd-key copy/paste.
- **Agent-driven setup** — central-mcp's runtime guidance (`~/.central-mcp/AGENTS.md`) tells the orchestrator how to call `cmux new-split` itself, so layout work is one natural-language instruction (*"set up watch panes for the current workspace"*) rather than a config file.

The end result: you're inside a real macOS app, your agent (Claude Code / Codex / Gemini / opencode) is already running in one cmux pane talking to central-mcp, and one sentence later there's a clean grid of project panes around it, each tailing live dispatch output. No tmux config, no key bindings to memorize, no terminal-emulator overhead.

---

## Quickstart with cmux

1. Install cmux from <https://github.com/manaflow-ai/cmux> (macOS).
2. Open cmux.app and create a workspace.
3. In the workspace's first pane, run `cmcp` to launch the orchestrator.
4. Tell the orchestrator: *"Set up watch panes for every project in the current workspace."*
5. The orchestrator reads `~/.central-mcp/AGENTS.md` (shipped with central-mcp on first launch — has the full cmux recipe), then calls `cmux new-split` once per project until the grid is laid out.

That's it. Each pane runs `cmcp watch <project>` and shows live event output for its project. You stay in the orchestrator pane and keep dispatching.

> The "single split per tool call, strictly sequential" rule lives in `data/AGENTS.md` and is what produces clean grids on any pane count from 1 to 8+. The orchestrator handles it for you.

---

## Quickstart with tmux or zellij

If you don't want the cmux GUI, both terminal backends are first-class:

```bash
cmcp up                    # interactive picker (tmux / zellij)
cmcp tmux                  # explicit
cmcp zellij                # explicit

cmcp tmux --workspace work # only show projects in workspace 'work'
cmcp tmux --all            # one session per workspace
```

- Session names are `cmcp-<workspace>` (e.g. `cmcp-work`).
- Pane 0 = orchestrator, panes 1+ = `cmcp watch <project>` per registered project.
- `cmcp down` tears the session back down.

Both backends are pure Python — no extra config files, no key bindings to learn.

---

## Common to all backends

`cmcp watch <project>` is what runs in every project pane:

- Tails `~/.central-mcp/logs/<project>/dispatch.jsonl` line-by-line.
- Sticky header with project name, current agent, status (idle / running / errored), elapsed time.
- ANSI-colored output: prose readable, code blocks magenta-tinted, fallback transitions yellow with `↻`.
- Filters known noise — Codex's status banners, Gemini's deprecation warnings, blank-line spam.

You can run it standalone in any single terminal too: `cmcp watch my-app`.

---

## Screenshots and demo

!!! info "Coming soon"
    Real cmux + central-mcp captures (4-up grid, mid-dispatch streaming, ~30s screen recording) will land here once the assets are recorded. Until then, the [cmux project page](https://github.com/manaflow-ai/cmux) has app-level screenshots and the recipe in `~/.central-mcp/AGENTS.md` (shipped with central-mcp) describes the exact flow.

<!--
  Drop the captures into docs/assets/observation/ and then replace the
  admonition above with the markdown below. Files expected:
    - cmux-grid.png        (4-up cmux grid: orchestrator + 3 watches)
    - cmux-dispatch.png    (mid-dispatch with live tokens streaming)
    - cmux-demo.mp4        (~30s recording of the full flow)

  ![cmux observation grid — orchestrator on the left, three live `cmcp watch` panes on the right](assets/observation/cmux-grid.png){ loading=lazy }

  *4-up cmux grid: the orchestrator handles prompts on one side; each project's `cmcp watch` pane shows live dispatch output on the other.*

  ![Mid-dispatch view with token stream](assets/observation/cmux-dispatch.png){ loading=lazy }

  *Mid-dispatch: per-project token totals tick upward in the sticky header; the body shows the agent's output as it streams.*

  <video src="assets/observation/cmux-demo.mp4" controls preload="metadata" style="max-width: 100%; border-radius: 8px;">
    Your browser doesn't support inline video. <a href="assets/observation/cmux-demo.mp4">Download the demo</a>.
  </video>

  *~30 second recording: launch `cmcp` in cmux → register two projects → fan-out the same prompt to both → watch the two panes work in parallel.*
-->

---

## Why bother with observation at all?

You don't have to. Dispatch is non-blocking, results piggyback on the next MCP tool call, and "any updates?" works any time. For 1–2 projects, just talking to the orchestrator is fine.

Where observation pays off:

- **3+ concurrent projects.** Watching live output catches a wedged agent in seconds instead of after the next "status?" prompt.
- **Long-running dispatches** (>2 minutes). Sticky-header elapsed-time prevents the "is it stuck or just slow?" anxiety.
- **Debugging an agent that's misbehaving** in one specific project — the per-pane log stream is far easier to read than a single mixed `orchestration_history` reply.

If none of those hit you, skip observation entirely. central-mcp works the same either way.
