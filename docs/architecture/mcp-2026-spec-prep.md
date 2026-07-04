# MCP 2026-07-28 spec preparation

Working notes for the [Ecosystem alignment](../ROADMAP.md#ecosystem-alignment)
roadmap track. The 2026-07-28 MCP release makes the protocol core
stateless and moves long-running work to an official **Tasks
extension** — the same `handle → poll → cancel` lifecycle central-mcp's
`dispatch` / `check_dispatch` / `cancel_dispatch` tools have used since
day one. This page records what we audited, what shipped in Phase 1,
and what Phases 2–3 still need.

## Phase 1 (shipped) — task-model groundwork

**`central_mcp.tasks_adapter`** is the pure translation layer between
the two vocabularies. No SDK imports; input is the dispatch-entry dict
shared by `server.py` and `dispatches_db._row_to_entry`, output is a
plain dict tracking the RC's task-object shape.

Status mapping (dispatch → Tasks lifecycle):

| dispatches.db `status` | Tasks status | terminal |
|---|---|---|
| `running`   | `working`   | no  |
| `complete`  | `completed` | yes |
| `error`     | `failed`    | yes |
| `timeout`   | `failed`    | yes |
| `cancelled` | `cancelled` | yes |

Notes on the mapping:

- **Unknown statuses map to `working`**, never to a terminal state — a
  future in-flight status misreported as terminal would make pollers
  abandon a live dispatch, which is the worse failure.
- **`input_required` has no dispatch equivalent yet.** PTY-mode
  dispatches blocked on a human answering a permission prompt are the
  natural future candidate (see the Live agent panes track).
- `pollInterval` is fixed at 3000 ms, matching the "poll
  `check_dispatch` every 3 s" guidance shipped in `data/CLAUDE.md`.
- central-mcp context (project, agent) rides in task `_meta` under the
  reverse-DNS key `io.github.andy5090.central-mcp/dispatch`, per the
  RC's metadata naming convention.

Contract is locked by `tests/test_tasks_adapter.py`, including a
round-trip through the real `dispatches_db` writers.

## Deprecated-feature audit (clean)

The 2026-07-28 release deprecates three core features with a 12-month
window: **Roots, Sampling, Logging**. Audit of `src/central_mcp/`
(2026-07-04, v0.12.2):

- No `sampling` / `create_message` usage.
- No `roots` / `list_roots` usage.
- No MCP-level logging (`notifications/message`) — all logging is
  process-local.
- Server surface is tools-only (plus instructions), built on
  `fastmcp.FastMCP`. Nothing to migrate.

## Phase 2 (next) — wire the Tasks extension, behind a flag

- We depend on **fastmcp**, not the official `mcp` python-sdk directly.
  The official SDK's v2 beta implements the full RC with a pluggable
  extensions API; Phase 2 needs a decision: wait for fastmcp to expose
  the extensions API, or serve the Tasks methods from a parallel
  official-SDK path. Spike required before committing.
- Serve `tasks/get` / `tasks/cancel` from the same `dispatches.db` rows
  via `tasks_adapter`; `dispatch` responses gain a task handle when the
  client advertises the extension.
- `check_dispatch` / `cancel_dispatch` remain unchanged — the extension
  is an additional wire shape over the same state, not a replacement.

## Phase 3 (on stable v2) — flip the default

- Pin the stable SDK, drop the flag, run the mechanical stateless-core
  conformance sweep (header validation, `ttlMs` / `cacheScope` on list
  responses — largely SDK-handled).
- central-mcp is already stateless between requests by design, so no
  architectural work is expected.
