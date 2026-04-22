# central-mcp — development guide

You are working on the central-mcp **codebase itself**. This file is for contributors (human or agent) editing the source tree. The runtime orchestrator instructions — the ones that describe how `dispatch` / `check_dispatch` should be used and what the observation layer does — live separately in `src/central_mcp/data/{CLAUDE,AGENTS}.md` and get copied to `~/.central-mcp/` on first launch. Don't confuse the two roles:

| File path | Role | Audience |
|---|---|---|
| `src/central_mcp/data/{CLAUDE,AGENTS}.md` | Runtime, shipped with the wheel | Orchestrator agent running inside a user's `~/.central-mcp/` session |
| `/{CLAUDE,AGENTS}.md` (repo root) | Dev-mode, NOT shipped | Anyone editing central-mcp's source |

## What central-mcp is

A Python MCP server + CLI that acts as an orchestrator-agnostic dispatch hub across a user's registered projects. Each project is associated with a coding-agent CLI (claude / codex / gemini / droid / opencode). Dispatches are non-blocking subprocesses in the project's cwd; results stream to `~/.central-mcp/logs/<project>/dispatch.jsonl` and can be tailed via `central-mcp watch <project>`.

Primary surfaces:
- **MCP tools** (`dispatch`, `check_dispatch`, `list_projects`, `orchestration_history`, `reorder_projects`, …) — defined in `src/central_mcp/server.py`.
- **CLI subcommands** (`run`, `up`, `tmux`, `zellij`, `down`, `watch`, `upgrade`, `add`, `remove`, `list`, `brief`, `install`, `alias`, `unalias`, `reorder`, `init`, `serve`) — wired in `src/central_mcp/cli/__init__.py`, implementation in `src/central_mcp/cli/_commands.py`.

## Repo layout

```
src/central_mcp/
  cli/
    __init__.py       argparse + entry point (`central-mcp`, `cmcp`)
    _commands.py      cmd_* handlers + shared helpers
  adapters/base.py    per-agent launch / session-list logic
  server.py           MCP tool definitions (stdio)
  registry.py         registry.yaml load / save / reorder
  layout.py           tmux multi-pane layout builder
  zellij.py           zellij KDL layout builder
  grid.py             shared terminal-size-derived pane math (tmux + zellij)
  watch.py            `central-mcp watch` jsonl streamer
  session_info.py     which-multiplexer-is-active stamp
  paths.py            $CENTRAL_MCP_HOME resolution cascade
  data/
    CLAUDE.md         RUNTIME orchestrator guideline (shipped)
    AGENTS.md         RUNTIME orchestrator guideline (shipped)
tests/                pytest suite (run: `uv run --no-sync pytest`)
docs/
  ROADMAP.md          phases / intent
  architecture/       deeper dives (gemini session storage, etc.)
CHANGELOG.md          Keep-a-Changelog; top block = unreleased when in-flight
pyproject.toml        `version = "X.Y.Z"` (hatchling)
README.md / README_KO.md  user-facing docs; absolute image URLs so PyPI renders them
```

## Testing

```bash
uv run --no-sync pytest            # full suite (~3s, ~226 tests)
uv run --no-sync pytest tests/test_adapters.py -v   # targeted
```

- `tests/conftest.py::fake_home` fixture isolates each test from the real `~/.central-mcp`.
- `tests/test_adapters_live.py` hits real agent CLIs — skipped unless you opt in.
- **No cmux tests exist.** The cmux backend is agent-driven (the orchestrator uses its Bash tool to call `cmux new-split` / `send` / `send-key`; central-mcp itself doesn't touch the cmux socket), so there's no Python code path to unit-test. Integration testing for cmux is manual (open cmux.app, run `cmcp` in a pane, ask the orchestrator to set up watch panes).

## Release flow

1. Add a `## [X.Y.Z] — YYYY-MM-DD` block to the top of `CHANGELOG.md` describing changes.
2. Bump `version = "X.Y.Z"` in `pyproject.toml`.
3. `uv run --no-sync pytest` — green.
4. `git commit -am 'chore(release): X.Y.Z'` (or combine with a feature commit).
5. `rm -rf dist && uv build`.
6. `git push origin main`.
7. **PyPI upload** — credentials are kept out of this file intentionally. See `.publish.md` (gitignored, local-only) for the exact command. If `.publish.md` doesn't exist yet, create it from the template in `.gitignore`'s comment or ask the agent to scaffold it.
8. If you edited `src/central_mcp/data/{CLAUDE,AGENTS}.md`, note the copy-on-miss caveat in the CHANGELOG: existing installs need `rm ~/.central-mcp/{CLAUDE,AGENTS}.md` before the next orchestrator launch to pick up the new bundle.

Patch-bump cadence is liberal (docs fixes, wording tweaks, small behavior changes). Minor bump for breaking CLI changes, new MCP tools, or backend architecture shifts.

## Key invariants (treat as load-bearing)

- **central-mcp is stateless between requests.** All state lives in `~/.central-mcp/registry.yaml` and per-dispatch jsonl logs. No in-memory "current project", no daemon.
- **Dispatch is non-blocking.** `dispatch()` spawns a subprocess and returns a `dispatch_id` in under 100ms. The caller polls `check_dispatch` (or background-agents it) to get results.
- **The observation layer is optional and user-initiated.** tmux (`central-mcp tmux`), zellij (`central-mcp zellij`), and cmux (agent-driven from inside cmux.app) are three separate paths. central-mcp never spawns observation panes on behalf of the user implicitly.
- **No `central-mcp cmux` subcommand.** cmux's CLI doesn't expose a declarative layout primitive we can use, and inline-seed-via-keystroke-injection proved too fragile. The workflow is: user launches cmux.app, runs `cmcp` in a pane, asks the orchestrator to set up watch panes — the recipe lives in `src/central_mcp/data/{CLAUDE,AGENTS}.md`. If you find yourself adding a cmux CLI command, reconsider (see CHANGELOG 0.8.1 for the rationale).
- **Orchestrator instructions live in `src/central_mcp/data/`, not at repo root.** When a user asks to update orchestrator behavior (session handling, reorder guidance, cmux recipe, etc.), edit those files — not the files you're reading right now.
- **`/{CLAUDE,AGENTS}.md` are NOT symlinks.** Earlier in the repo's history they were set up as symlinks into `src/central_mcp/data/`, which caused an editor-level clobber (writing to root silently overwrote the shipped runtime file). Keep them as separate real files with separate content.

## Working on this repo

Unlike a dispatch-router context, you have full tool access: Read, Edit, Write, Bash, Grep, Glob, Agent. Tests should cover behavior changes where practical; the suite runs in ~3s so add-and-run-often is the right cadence. When in doubt about CLI syntax or wire format for external tools (cmux, claude, codex, gemini), `<tool> --help` first — don't trust memory.

Editable install vs PyPI:
- `uv run --no-sync central-mcp <cmd>` uses the project's editable venv (source tree wins).
- Shell `central-mcp` resolves to the uv-tool install; re-point at the editable source with `uv tool install --reinstall --editable /Users/andy/Projects/central-mcp` if you want the global shell to track local edits.
