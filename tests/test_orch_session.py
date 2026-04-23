"""Tests for `central_mcp.orch_session` — orchestrator token backfill."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from central_mcp import orch_session, registry, tokens_db


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _claude_turn(
    ts: str, session_id: str, request_id: str, cwd: str,
    input_tokens: int, output_tokens: int,
) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": session_id,
        "requestId": request_id,
        "cwd": cwd,
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }


# ── Claude reader ────────────────────────────────────────────────────────────

class TestClaudeReader:
    def test_extracts_assistant_turn_tokens(self, tmp_path: Path) -> None:
        session = tmp_path / "abc.jsonl"
        _write_jsonl(session, [
            {"type": "user", "message": {"content": "hi"}},
            _claude_turn("2026-04-24T10:00:00Z", "s1", "r1",
                         "/cwd", 100, 50),
            _claude_turn("2026-04-24T10:05:00Z", "s1", "r2",
                         "/cwd", 200, 30),
            # A `user` turn must be ignored.
            {"type": "user", "message": {"content": "ok"}},
        ])
        turns = list(orch_session._iter_claude_turns(session))
        assert len(turns) == 2
        assert turns[0]["input"] == 100
        assert turns[0]["output"] == 50
        assert turns[0]["total"] == 150
        assert turns[0]["session_id"] == "s1"
        assert turns[0]["request_id"] == "r1"
        assert turns[1]["input"] == 200

    def test_missing_usage_skipped(self, tmp_path: Path) -> None:
        session = tmp_path / "x.jsonl"
        _write_jsonl(session, [
            {"type": "assistant", "timestamp": "t", "sessionId": "s",
             "message": {"usage": {}}},    # no input/output
        ])
        assert list(orch_session._iter_claude_turns(session)) == []

    def test_malformed_lines_tolerated(self, tmp_path: Path) -> None:
        session = tmp_path / "mixed.jsonl"
        session.parent.mkdir(parents=True, exist_ok=True)
        good = _claude_turn("t", "s", "r", "/x", 1, 2)
        session.write_text(
            "not json\n" + json.dumps(good) + "\n{ bad\n",
            encoding="utf-8",
        )
        assert len(list(orch_session._iter_claude_turns(session))) == 1

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert list(orch_session._iter_claude_turns(tmp_path / "no.jsonl")) == []


# ── Codex reader ─────────────────────────────────────────────────────────────

class TestCodexReader:
    def test_reads_token_count_events(self, tmp_path: Path) -> None:
        session = tmp_path / "rollout.jsonl"
        _write_jsonl(session, [
            {"type": "session_meta", "timestamp": "t0",
             "payload": {"id": "sess-1", "cwd": "/project"}},
            {"type": "event_msg", "timestamp": "t1",
             "payload": {"type": "token_count",
                         "info": {"last_token_usage": {
                             "input_tokens": 1000,
                             "output_tokens": 50,
                             "total_tokens": 1050,
                             "cached_input_tokens": 200,
                         }}}},
            {"type": "event_msg", "timestamp": "t2",
             "payload": {"type": "token_count",
                         "info": {"last_token_usage": {
                             "input_tokens": 2000,
                             "output_tokens": 100,
                             "total_tokens": 2100,
                         }}}},
        ])
        turns = list(orch_session._iter_codex_turns(session))
        assert len(turns) == 2
        assert turns[0]["session_id"] == "sess-1"
        assert turns[0]["cwd"] == "/project"
        assert turns[0]["total"] == 1050
        assert turns[0]["cache_read"] == 200
        assert turns[0]["request_id"] == "turn-1"
        assert turns[1]["request_id"] == "turn-2"

    def test_empty_token_count_info_skipped(self, tmp_path: Path) -> None:
        session = tmp_path / "r.jsonl"
        _write_jsonl(session, [
            {"type": "session_meta", "payload": {"id": "s", "cwd": "/x"}},
            {"type": "event_msg",
             "payload": {"type": "token_count", "info": None}},
        ])
        assert list(orch_session._iter_codex_turns(session)) == []


# ── project mapping ──────────────────────────────────────────────────────────

class TestProjectForCwd:
    def test_matches_registered_project(self, fake_home: Path, tmp_path: Path) -> None:
        pdir = tmp_path / "alpha"
        pdir.mkdir()
        registry.add_project("alpha", str(pdir))
        assert orch_session._project_for_cwd(str(pdir)) == "alpha"

    def test_unmatched_cwd_returns_none(self, fake_home: Path) -> None:
        assert orch_session._project_for_cwd("/not/registered") is None

    def test_empty_cwd_returns_none(self, fake_home: Path) -> None:
        assert orch_session._project_for_cwd("") is None


# ── sync_orchestrator integration ────────────────────────────────────────────

class TestOpencodeReader:
    """opencode's reader is hybrid: SQLite peek (3 stable columns) for
    discovery, then `opencode export` subprocess for the content. We
    stub both so the test doesn't need an opencode install.
    """

    def _make_db(self, tmp_path: Path, session_id: str, directory: str) -> Path:
        import sqlite3
        db = tmp_path / "opencode.db"
        with sqlite3.connect(str(db)) as conn:
            conn.execute("""
                CREATE TABLE session (
                    id text PRIMARY KEY,
                    directory text NOT NULL,
                    time_updated integer NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO session VALUES (?, ?, ?)",
                (session_id, directory, 1770000000000),
            )
        return db

    def _export_payload(self, session_id: str, directory: str) -> str:
        return "Exporting session: abc\n" + json.dumps({
            "info": {"id": session_id, "directory": directory},
            "messages": [
                {
                    "info": {"role": "assistant", "id": "msg_1",
                             "time": {"completed": "2026-04-24T10:00:00Z"}},
                    "parts": [
                        {"type": "text", "text": "Hi"},
                        {"type": "step-finish", "id": "prt_1",
                         "tokens": {"total": 150, "input": 100, "output": 50,
                                    "cache": {"read": 20, "write": 0}}},
                    ],
                },
                {
                    "info": {"role": "assistant", "id": "msg_2",
                             "time": {"completed": "2026-04-24T10:05:00Z"}},
                    "parts": [
                        {"type": "step-finish", "id": "prt_2",
                         "tokens": {"total": 230, "input": 200, "output": 30}},
                    ],
                },
            ],
        })

    def test_extracts_step_finish_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = self._make_db(tmp_path, "ses_1", "/proj")
        payload = self._export_payload("ses_1", "/proj")

        class _R:
            def __init__(self, stdout, rc=0):
                self.stdout, self.returncode = stdout, rc
        monkeypatch.setattr(
            orch_session.__dict__.setdefault("subprocess", __import__("subprocess")),
            "run", lambda *a, **kw: _R(payload),
        )
        # Easier: patch the subprocess module reference inside orch_session.
        import subprocess as _sp
        monkeypatch.setattr(_sp, "run", lambda *a, **kw: _R(payload))

        turns = list(orch_session._iter_opencode_turns(db))
        assert len(turns) == 2
        assert turns[0]["total"] == 150
        assert turns[0]["input"] == 100
        assert turns[0]["cache_read"] == 20
        assert turns[0]["session_id"] == "ses_1"
        assert turns[0]["cwd"] == "/proj"
        assert turns[1]["total"] == 230

    def test_missing_db_returns_nothing(self, tmp_path: Path) -> None:
        assert list(orch_session._iter_opencode_turns(tmp_path / "no.db")) == []

    def test_export_failure_returns_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = self._make_db(tmp_path, "ses_x", "/x")
        class _R:
            stdout = ""
            returncode = 1
        import subprocess as _sp
        monkeypatch.setattr(_sp, "run", lambda *a, **kw: _R())
        assert list(orch_session._iter_opencode_turns(db)) == []


class TestSyncOrchestrator:
    def test_unsupported_agent_is_noop(self, fake_home: Path) -> None:
        assert orch_session.sync_orchestrator("gemini") == 0
        assert orch_session.sync_orchestrator("") == 0

    def test_no_session_files_is_noop(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Point HOME at an empty dir so no session files exist.
        monkeypatch.setenv("HOME", str(tmp_path))
        assert orch_session.sync_orchestrator("claude") == 0

    def test_claude_sync_inserts_rows(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        session_dir = tmp_path / ".claude" / "projects" / "-project-alpha"
        session = session_dir / "sess-1.jsonl"
        _write_jsonl(session, [
            _claude_turn("2026-04-24T10:00:00Z", "sess-1", "r1",
                         "/project/alpha", 100, 50),
            _claude_turn("2026-04-24T10:05:00Z", "sess-1", "r2",
                         "/project/alpha", 200, 30),
        ])
        registry.add_project("alpha", "/project/alpha")

        n = orch_session.sync_orchestrator("claude")
        assert n == 2

        # Rows landed in tokens.db with source='orchestrator' + matched project.
        with tokens_db._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage WHERE source='orchestrator' ORDER BY request_id"
            ).fetchall()
        assert len(rows) == 2
        assert rows[0]["project"] == "alpha"
        assert rows[0]["agent"] == "claude"
        assert rows[0]["total_tokens"] == 150
        assert rows[1]["total_tokens"] == 230

    def test_dedup_on_second_sync(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        session_dir = tmp_path / ".claude" / "projects" / "-x"
        session = session_dir / "s.jsonl"
        _write_jsonl(session, [
            _claude_turn("t1", "s", "r1", "/x", 10, 5),
            _claude_turn("t2", "s", "r2", "/x", 20, 10),
        ])

        orch_session.sync_orchestrator("claude")
        orch_session.sync_orchestrator("claude")   # second pass

        with tokens_db._connect() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM usage WHERE source='orchestrator'"
            ).fetchone()["n"]
        assert n == 2, "UNIQUE constraint should dedup re-syncs"
