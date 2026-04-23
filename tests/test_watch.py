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


def _render(record: dict, states: dict | None = None) -> str:
    buf = io.StringIO()
    watch._render(record, buf, states)
    return buf.getvalue()


def _render_seq(*records: dict) -> str:
    """Render multiple records sharing one state dict (simulates a stream)."""
    states: dict = {}
    buf = io.StringIO()
    for r in records:
        watch._render(r, buf, states)
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

    def test_attempt_start_shows_fallback_arrow(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:46.000+00:00",
            "id": "x", "event": "attempt_start",
            "agent": "codex",
        })
        assert "codex" in out
        assert "fallback" in out
        assert "↻" in out

    def test_output_spinner_is_skipped(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:46.000+00:00",
            "id": "x", "event": "output",
            "stream": "stdout", "chunk": "⠋",
        })
        assert out == ""  # spinner lines produce no output

    def test_output_blank_line_is_kept(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:46.000+00:00",
            "id": "x", "event": "output",
            "stream": "stdout", "chunk": "",
        })
        # Blank lines are intentional spacing — kept.
        assert "\n" in out

    def test_complete_shows_tokens_when_present(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:49.000+00:00",
            "id": "abc", "event": "complete",
            "ok": True, "status": "complete", "exit_code": 0,
            "duration_sec": 3.0, "agent_used": "claude",
            "tokens": {"input": 1234, "output": 567, "total": 1801},
        })
        assert "1,801" in out or "tokens=1,801" in out

    def test_complete_no_tokens_field_when_absent(self) -> None:
        out = _render({
            "ts": "2026-04-18T10:23:49.000+00:00",
            "id": "abc", "event": "complete",
            "ok": True, "status": "complete",
        })
        assert "tokens" not in out

    def test_state_tracks_done_across_records(self) -> None:
        """done flag set by complete event persists in shared states dict."""
        states: dict = {}
        _render({"id": "x", "event": "start", "ts": "", "agent": "claude", "prompt": "", "chain": ["claude"]}, states)
        _render({"id": "x", "event": "complete", "ts": "", "ok": True, "status": "complete"}, states)
        assert states["x"].done is True

    def test_state_stores_agent_on_start(self) -> None:
        states: dict = {}
        _render({"id": "x", "event": "start", "ts": "", "agent": "codex", "prompt": "", "chain": ["codex"]}, states)
        assert states["x"].agent == "codex"


class TestAgentNoise:
    """Agent-specific metadata lines are DIM-colored, not skipped."""

    def _render_output(self, chunk: str, agent: str) -> str:
        """Simulate: start → output for a given agent."""
        states: dict = {}
        buf = io.StringIO()
        watch._render({"id": "x", "event": "start", "ts": "", "agent": agent, "prompt": "", "chain": [agent]}, buf, states)
        watch._render({"id": "x", "event": "output", "ts": "", "stream": "stdout", "chunk": chunk}, buf, states)
        return buf.getvalue()

    def test_codex_workdir_line_is_dimmed(self, monkeypatch) -> None:
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "DIM", lambda s: f"[DIM]{s}[/DIM]")
        out = self._render_output("workdir: /Users/andy/Projects/myapp", "codex")
        assert "[DIM]workdir: /Users/andy/Projects/myapp[/DIM]" in out

    def test_codex_model_line_is_dimmed(self, monkeypatch) -> None:
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "DIM", lambda s: f"[DIM]{s}[/DIM]")
        out = self._render_output("model: o4-mini", "codex")
        assert "[DIM]model: o4-mini[/DIM]" in out

    def test_codex_separator_is_dimmed(self, monkeypatch) -> None:
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "DIM", lambda s: f"[DIM]{s}[/DIM]")
        out = self._render_output("--------", "codex")
        assert "[DIM]--------[/DIM]" in out

    def test_codex_separator_not_skipped(self, monkeypatch) -> None:
        """Codex separator appears (dimmed), unlike a spinner which produces no output."""
        monkeypatch.setattr(watch, "_IS_TTY", False)
        out = self._render_output("--------", "codex")
        assert "--------" in out

    def test_gemini_warn_line_is_dimmed(self, monkeypatch) -> None:
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "DIM", lambda s: f"[DIM]{s}[/DIM]")
        out = self._render_output("[WARN] some warning message", "gemini")
        assert "[DIM][WARN] some warning message[/DIM]" in out

    def test_gemini_yolo_line_is_dimmed(self, monkeypatch) -> None:
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "DIM", lambda s: f"[DIM]{s}[/DIM]")
        out = self._render_output("YOLO mode is enabled.", "gemini")
        assert "[DIM]YOLO mode is enabled.[/DIM]" in out

    def test_claude_separator_not_dimmed(self, monkeypatch) -> None:
        """Codex-specific separator is NOT dimmed for claude agent."""
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "DIM", lambda s: f"[DIM]{s}[/DIM]")
        out = self._render_output("--------", "claude")
        assert "[DIM]--------[/DIM]" not in out
        assert "--------" in out

    def test_normal_content_not_dimmed_for_codex(self, monkeypatch) -> None:
        monkeypatch.setattr(watch, "_IS_TTY", True)
        monkeypatch.setattr(watch, "DIM", lambda s: f"[DIM]{s}[/DIM]")
        out = self._render_output("Here is the fixed code:", "codex")
        assert "[DIM]Here is the fixed code:[/DIM]" not in out
        assert "Here is the fixed code:" in out


class TestTokenExtraction:
    def test_claude_format(self) -> None:
        from central_mcp.server import _extract_token_usage
        out = "Tokens: 2,341 input · 234 output\nDone."
        result = _extract_token_usage(out)
        assert result == {"input": 2341, "output": 234, "total": 2575}

    def test_claude_comma_separator(self) -> None:
        from central_mcp.server import _extract_token_usage
        out = "Tokens: 1000 input, 500 output"
        result = _extract_token_usage(out)
        assert result == {"input": 1000, "output": 500, "total": 1500}

    def test_generic_tokens_format(self) -> None:
        from central_mcp.server import _extract_token_usage
        out = "Used 800 input tokens, 200 output tokens."
        result = _extract_token_usage(out)
        assert result == {"input": 800, "output": 200, "total": 1000}

    def test_total_only(self) -> None:
        from central_mcp.server import _extract_token_usage
        out = "Total tokens: 1500"
        result = _extract_token_usage(out)
        assert result == {"total": 1500}

    def test_no_match_returns_none(self) -> None:
        from central_mcp.server import _extract_token_usage
        result = _extract_token_usage("No token info here.")
        assert result is None

    def test_empty_returns_none(self) -> None:
        from central_mcp.server import _extract_token_usage
        assert _extract_token_usage("") is None
        assert _extract_token_usage(None) is None  # type: ignore[arg-type]
