"""Tests for `central-mcp watch` (central_mcp.watch).

The render side is pure (record → text), so we test it by feeding
synthetic records into `_render` and asserting the output shape.
The tail loop is exercised by the dispatch E2E tests elsewhere.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from central_mcp import watch


def _render(record: dict) -> str:
    buf = io.StringIO()
    watch._render(record, buf)
    return buf.getvalue()


class TestRender:
    def test_start_event_includes_prompt_and_agent(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:45.000+00:00",
            "id": "abc12345",
            "event": "start",
            "agent": "claude",
            "prompt": "fix the bug",
            "chain": ["claude"],
        })
        assert "abc12345" in out
        assert "start" in out
        assert "claude" in out
        assert "fix the bug" in out
        assert "10:23:45" in out

    def test_start_shows_fallback_chain_only_when_multiple(self) -> None:
        single = _render({
            "ts": "2026-04-18T10:23:45.000+00:00",
            "id": "x", "event": "start",
            "agent": "claude", "prompt": "p",
            "chain": ["claude"],
        })
        multi = _render({
            "ts": "2026-04-18T10:23:45.000+00:00",
            "id": "x", "event": "start",
            "agent": "claude", "prompt": "p",
            "chain": ["claude", "codex"],
        })
        assert "→" not in single
        assert "→" in multi
        assert "codex" in multi

    def test_output_stdout_uncolored(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:46.000+00:00",
            "id": "x", "event": "output",
            "stream": "stdout", "chunk": "hello",
        })
        assert "hello" in out

    def test_output_stderr_gets_red_in_tty(self, monkeypatch) -> None:
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "RED", lambda s: f"[RED]{s}[/RED]")
        out = _render({
            "ts": "2026-04-18T10:23:46.000+00:00",
            "id": "x", "event": "output",
            "stream": "stderr", "chunk": "oops",
        })
        assert "[RED]oops[/RED]" in out

    def test_complete_success_summary(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:49.000+00:00",
            "id": "abc", "event": "complete",
            "ok": True, "status": "complete", "exit_code": 0,
            "duration_sec": 2.3, "agent_used": "claude",
        })
        assert "done" in out
        assert "abc" in out
        assert "2.3s" in out
        assert "exit=0" in out
        assert "claude" in out

    def test_complete_failure_shows_error(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:49.000+00:00",
            "id": "abc", "event": "complete",
            "ok": False, "status": "error", "exit_code": 1,
            "duration_sec": 0.5, "error": "boom",
        })
        assert "failed" in out or "✗" in out
        assert "boom" in out

    def test_complete_timeout_distinct_from_failure(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:49.000+00:00",
            "id": "abc", "event": "complete",
            "ok": False, "status": "timeout",
            "duration_sec": 600.0,
        })
        assert "timeout" in out.lower()

    def test_error_event(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:49.000+00:00",
            "id": "abc", "event": "error",
            "error": "unexpected exception",
        })
        assert "unexpected exception" in out


