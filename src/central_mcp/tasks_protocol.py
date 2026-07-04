"""Experimental MCP Tasks protocol handlers backed by dispatch state.

Phase 2 of the roadmap's "Ecosystem alignment" track: serve
`tasks/get` / `tasks/cancel` / `tasks/result` from the same dispatch
records that back `check_dispatch` / `cancel_dispatch`. The extension
is an additional wire shape over the same state, not a replacement —
the classic tools are untouched whether or not this is enabled.

Gated behind `CENTRAL_MCP_TASKS=1` because the wire shape tracks the
experimental Tasks protocol in the installed SDK (mcp 1.x, spec
2025-11-25). The 2026-07-28 release moves Tasks to an official
extension with the same get/cancel polling lifecycle; when fastmcp /
the SDK ship that shape, this module migrates and the flag flips to
default-on (roadmap Phase 3).

Task IDs are dispatch IDs — `dispatch()` returns `dispatch_id`, and a
Tasks-speaking client polls `tasks/get {taskId: <dispatch_id>}`.

fastmcp's own task support (`_setup_task_protocol_handlers`) is
docket-backed and runs *fastmcp tools* as background tasks; it is not
installed here. We register our handlers the same way fastmcp does —
directly on the lowlevel SDK server's `request_handlers` map.
"""

from __future__ import annotations

import os
from typing import Any, Callable

FLAG_ENV = "CENTRAL_MCP_TASKS"

LookupFn = Callable[[str], "dict[str, Any] | None"]
CancelFn = Callable[[str], "dict[str, Any]"]


def enabled() -> bool:
    return os.environ.get(FLAG_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def maybe_setup(mcp: Any, lookup: LookupFn, cancel: CancelFn) -> bool:
    """Register Tasks handlers on `mcp` if the flag is set.

    `lookup(dispatch_id)` returns the dispatch-entry dict (memory-first,
    db fallback) or None. `cancel(dispatch_id)` requests cancellation
    and returns the classic cancel_dispatch response dict.

    Returns True if handlers were registered.
    """
    if not enabled():
        return False

    from mcp.shared.exceptions import McpError
    from mcp.types import (
        INVALID_PARAMS,
        CancelTaskRequest,
        CancelTaskResult,
        ErrorData,
        GetTaskPayloadRequest,
        GetTaskPayloadResult,
        GetTaskRequest,
        GetTaskResult,
        ServerResult,
    )

    from central_mcp import tasks_adapter

    def _entry_or_error(task_id: str) -> dict[str, Any]:
        entry = lookup(task_id)
        if entry is None:
            raise McpError(ErrorData(
                code=INVALID_PARAMS,
                message=f"no task (dispatch) with id {task_id!r}",
            ))
        return entry

    async def handle_get(req: GetTaskRequest) -> ServerResult:
        entry = _entry_or_error(req.params.taskId)
        return ServerResult(
            GetTaskResult.model_validate(tasks_adapter.to_task(entry))
        )

    async def handle_cancel(req: CancelTaskRequest) -> ServerResult:
        task_id = req.params.taskId
        _entry_or_error(task_id)
        cancel(task_id)
        # Re-read: for an in-flight dispatch the kill is asynchronous
        # (the background thread finalizes to "cancelled"), so the
        # honest answer right now may still be "working".
        entry = _entry_or_error(task_id)
        return ServerResult(
            CancelTaskResult.model_validate(tasks_adapter.to_task(entry))
        )

    async def handle_result(req: GetTaskPayloadRequest) -> ServerResult:
        entry = _entry_or_error(req.params.taskId)
        status = tasks_adapter.task_status(entry.get("status"))
        if not tasks_adapter.is_terminal(status):
            raise McpError(ErrorData(
                code=INVALID_PARAMS,
                message=(
                    f"task {req.params.taskId!r} is still {status}; "
                    "poll tasks/get until it reaches a terminal status"
                ),
            ))
        result = entry.get("result") or {}
        text = result.get("output") or result.get("error") or ""
        return ServerResult(GetTaskPayloadResult.model_validate({
            "content": [{"type": "text", "text": text}],
            "isError": status != "completed",
        }))

    handlers = mcp._mcp_server.request_handlers
    handlers[GetTaskRequest] = handle_get
    handlers[CancelTaskRequest] = handle_cancel
    handlers[GetTaskPayloadRequest] = handle_result
    # tasks/list is deliberately NOT registered: the 2026-07-28 release
    # removes it (unscopable without sessions) — list_dispatches covers
    # the need at the tool layer.
    return True
