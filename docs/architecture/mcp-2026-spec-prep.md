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

## Phase 2 (shipped) — Tasks wire, behind a flag

The spike resolved the fastmcp-vs-official-SDK question in our favor:
fastmcp 3.x already sits on mcp 1.x, which ships the **experimental
Tasks protocol types** from the 2025-11-25 spec (`tasks/get`,
`tasks/cancel`, `tasks/result`, the full status vocabulary). fastmcp's
own task support is docket-backed and runs fastmcp tools as background
tasks — not what we need — but it demonstrates the registration
pattern: handlers go directly on the lowlevel SDK server's
`request_handlers` map.

**`central_mcp.tasks_protocol`** does exactly that, gated behind
`CENTRAL_MCP_TASKS=1`:

- `tasks/get {taskId}` → `GetTaskResult` via `tasks_adapter.to_task`;
  taskId is the dispatch_id returned by `dispatch`.
- `tasks/cancel {taskId}` → shared `_cancel_impl` (same code path as
  the `cancel_dispatch` tool), then re-reads state — the kill is
  asynchronous, so the honest immediate answer may still be `working`.
- `tasks/result {taskId}` → tool-result-shaped payload
  (`content` / `isError`) once terminal; INVALID_PARAMS while running.
- `tasks/list` is deliberately **not** served — the 2026-07-28 release
  removes it, and `list_dispatches` covers the need at the tool layer.

Flag off → `maybe_setup` is a no-op and the server is byte-identical
to before. Contract locked by `tests/test_tasks_protocol.py`.

Known gaps (accepted until Phase 3):

- No capability advertisement (`ServerTasksCapability`) — fastmcp owns
  the initialize response; clients discover task support out-of-band.
- `dispatch` does not return a `CreateTaskResult` task handle — the
  wire is poll-only, driven by the dispatch_id the tool already returns.
- The wire shape is the 2025-11-25 experimental protocol, not the final
  extension model.

## Phase 3 (on stable v2) — migrate shape + flip the default

- When fastmcp / the official SDK ship the final extension model:
  migrate handlers from the experimental core-protocol shape to the
  official Tasks extension, add capability advertisement, return task
  handles from `tools/call`, drop the flag.
- Run the mechanical stateless-core conformance sweep (header
  validation, `ttlMs` / `cacheScope` on list responses — largely
  SDK-handled).
- central-mcp is already stateless between requests by design, so no
  architectural work is expected.
