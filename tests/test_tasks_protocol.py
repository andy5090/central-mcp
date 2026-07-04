"""Tests for `central_mcp.tasks_protocol` — experimental Tasks wire.

The claim: with `CENTRAL_MCP_TASKS=1`, a Tasks-speaking MCP client can
drive a dispatch through tasks/get / tasks/cancel / tasks/result using
the dispatch_id as taskId, against the exact same state the classic
check_dispatch / cancel_dispatch tools read. Flag off → nothing is
registered and the server is byte-identical to before.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastmcp import FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import (
    CancelTaskRequest,
    CancelTaskRequestParams,
    GetTaskPayloadRequest,
    GetTaskPayloadRequestParams,
    GetTaskRequest,
    GetTaskRequestParams,
)

from central_mcp import dispatches_db, tasks_protocol


def _start_dispatch(did: str = "tp000001", status_after: str | None = None) -> None:
    dispatches_db.upsert_started(
        {
            "id":      did,
            "project": "myproj",
            "agent":   "claude",
            "chain":   ["claude"],
            "prompt":  "do the thing",
            "command": "claude -p 'do the thing'",
            "status":  "running",
            "started": time.time(),
        }
    )
    if status_after == "complete":
        dispatches_db.upsert_finished(
            did, "complete", {"ok": True, "exit_code": 0, "output": "all done"}
        )
    elif status_after == "error":
        dispatches_db.upsert_finished(
            did, "error", {"ok": False, "error": "exit 1"}
        )


def _setup(monkeypatch, cancel=None) -> FastMCP:
    monkeypatch.setenv(tasks_protocol.FLAG_ENV, "1")
    mcp = FastMCP("test")
    registered = tasks_protocol.maybe_setup(
        mcp,
        lookup=dispatches_db.get,
        cancel=cancel or (lambda did: {"ok": True, "cancelled": did}),
    )
    assert registered is True
    return mcp


def _call(mcp: FastMCP, request_cls, request):
    handler = mcp._mcp_server.request_handlers[request_cls]
    return asyncio.run(handler(request)).root


class TestFlagGate:
    def test_flag_off_registers_nothing(self, monkeypatch) -> None:
        monkeypatch.delenv(tasks_protocol.FLAG_ENV, raising=False)
        mcp = FastMCP("test")
        before = set(mcp._mcp_server.request_handlers)
        assert tasks_protocol.maybe_setup(
            mcp, lookup=lambda d: None, cancel=lambda d: {}
        ) is False
        assert set(mcp._mcp_server.request_handlers) == before
        assert GetTaskRequest not in mcp._mcp_server.request_handlers

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_flag_values(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv(tasks_protocol.FLAG_ENV, value)
        assert tasks_protocol.enabled() is True

    def test_tasks_list_not_registered(self, monkeypatch, fake_home: Path) -> None:
        # 2026-07-28 removes tasks/list; we never grow the surface.
        from mcp.types import ListTasksRequest
        mcp = _setup(monkeypatch)
        assert ListTasksRequest not in mcp._mcp_server.request_handlers


class TestGetTask:
    def test_running_dispatch(self, monkeypatch, fake_home: Path) -> None:
        _start_dispatch()
        mcp = _setup(monkeypatch)
        result = _call(mcp, GetTaskRequest, GetTaskRequest(
            method="tasks/get",
            params=GetTaskRequestParams(taskId="tp000001"),
        ))
        assert result.taskId == "tp000001"
        assert result.status == "working"
        assert result.pollInterval == 3000

    def test_completed_dispatch(self, monkeypatch, fake_home: Path) -> None:
        _start_dispatch(status_after="complete")
        mcp = _setup(monkeypatch)
        result = _call(mcp, GetTaskRequest, GetTaskRequest(
            method="tasks/get",
            params=GetTaskRequestParams(taskId="tp000001"),
        ))
        assert result.status == "completed"

    def test_unknown_id_raises_invalid_params(
        self, monkeypatch, fake_home: Path
    ) -> None:
        mcp = _setup(monkeypatch)
        with pytest.raises(McpError, match="no task"):
            _call(mcp, GetTaskRequest, GetTaskRequest(
                method="tasks/get",
                params=GetTaskRequestParams(taskId="nope"),
            ))


class TestCancelTask:
    def test_cancel_invokes_impl_and_returns_state(
        self, monkeypatch, fake_home: Path
    ) -> None:
        _start_dispatch()
        seen: list[str] = []

        def cancel(did: str) -> dict:
            seen.append(did)
            # Owning process finalizes asynchronously; simulate it done.
            dispatches_db.upsert_finished(did, "cancelled", {"ok": False})
            return {"ok": True, "cancelled": did}

        mcp = _setup(monkeypatch, cancel=cancel)
        result = _call(mcp, CancelTaskRequest, CancelTaskRequest(
            method="tasks/cancel",
            params=CancelTaskRequestParams(taskId="tp000001"),
        ))
        assert seen == ["tp000001"]
        assert result.status == "cancelled"


class TestTaskResult:
    def test_result_while_running_is_an_error(
        self, monkeypatch, fake_home: Path
    ) -> None:
        _start_dispatch()
        mcp = _setup(monkeypatch)
        with pytest.raises(McpError, match="still working"):
            _call(mcp, GetTaskPayloadRequest, GetTaskPayloadRequest(
                method="tasks/result",
                params=GetTaskPayloadRequestParams(taskId="tp000001"),
            ))

    def test_result_of_completed_dispatch(
        self, monkeypatch, fake_home: Path
    ) -> None:
        _start_dispatch(status_after="complete")
        mcp = _setup(monkeypatch)
        result = _call(mcp, GetTaskPayloadRequest, GetTaskPayloadRequest(
            method="tasks/result",
            params=GetTaskPayloadRequestParams(taskId="tp000001"),
        ))
        dumped = result.model_dump(exclude_none=True)
        assert dumped["content"] == [{"type": "text", "text": "all done"}]
        assert dumped["isError"] is False

    def test_result_of_failed_dispatch(
        self, monkeypatch, fake_home: Path
    ) -> None:
        _start_dispatch(status_after="error")
        mcp = _setup(monkeypatch)
        result = _call(mcp, GetTaskPayloadRequest, GetTaskPayloadRequest(
            method="tasks/result",
            params=GetTaskPayloadRequestParams(taskId="tp000001"),
        ))
        dumped = result.model_dump(exclude_none=True)
        assert dumped["isError"] is True
        assert dumped["content"][0]["text"] == "exit 1"


class TestServerWiring:
    def test_server_module_imports_with_flag_on(self, monkeypatch) -> None:
        # server.py calls maybe_setup at import time; flag on must not
        # break import (idempotence: module may already be imported, so
        # exercise maybe_setup against the live server object instead).
        monkeypatch.setenv(tasks_protocol.FLAG_ENV, "1")
        from central_mcp import server
        assert tasks_protocol.maybe_setup(
            server.mcp, lookup=server._lookup_entry, cancel=server._cancel_impl
        ) is True
        assert GetTaskRequest in server.mcp._mcp_server.request_handlers
