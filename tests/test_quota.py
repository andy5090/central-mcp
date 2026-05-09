"""Tests for the central_mcp.quota package.

Covers the auth-file parsing branches of each fetcher (not the live HTTP
calls — those are tested only at the "file-missing → None" and
"malformed → error" levels, which are the paths most likely to regress).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from central_mcp.quota import claude as claude_q
from central_mcp.quota import codex as codex_q
from central_mcp.quota import gemini as gemini_q


# ── claude ────────────────────────────────────────────────────────────────────

class TestClaudeFetch:
    def test_returns_api_key_when_credentials_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(claude_q, "_cred_path", lambda: tmp_path / "missing.json")
        # Disable keychain fallback too — on macOS dev machines the real
        # keychain may carry a token, which would defeat this test.
        monkeypatch.setattr(claude_q, "_read_token_from_keychain", lambda: None)
        assert claude_q.fetch() == {"mode": "api_key"}

    def test_keychain_fallback_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File missing → keychain returns a token → call goes out."""
        monkeypatch.setattr(claude_q, "_cred_path", lambda: tmp_path / "missing.json")
        monkeypatch.setattr(
            claude_q, "_read_token_from_keychain",
            lambda: "tok-from-keychain",
        )
        # Block the HTTP call — we just want to verify the token path.
        def _boom(*_a, **_k):
            raise RuntimeError("network disabled in tests")
        monkeypatch.setattr(claude_q.urllib.request, "urlopen", _boom)
        result = claude_q.fetch()
        assert result["mode"] == "pro"
        assert "error" in result

    def test_returns_error_on_malformed_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cred = tmp_path / "creds.json"
        cred.write_text("{ not json", encoding="utf-8")
        monkeypatch.setattr(claude_q, "_cred_path", lambda: cred)
        result = claude_q.fetch()
        assert result["mode"] == "error"
        assert "unreadable" in result["error"]

    def test_accepts_root_level_access_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cred = tmp_path / "creds.json"
        cred.write_text(json.dumps({"accessToken": "tok-root"}), encoding="utf-8")
        monkeypatch.setattr(claude_q, "_cred_path", lambda: cred)
        # Block the HTTP call so we verify token-reading, not network.
        def _boom(*_a, **_k):
            raise RuntimeError("network disabled in tests")
        monkeypatch.setattr(claude_q.urllib.request, "urlopen", _boom)
        result = claude_q.fetch()
        assert result["mode"] == "pro"
        assert "error" in result

    def test_accepts_nested_claudeaioauth_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cred = tmp_path / "creds.json"
        cred.write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "tok-nested"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(claude_q, "_cred_path", lambda: cred)
        def _boom(*_a, **_k):
            raise RuntimeError("network disabled in tests")
        monkeypatch.setattr(claude_q.urllib.request, "urlopen", _boom)
        result = claude_q.fetch()
        assert result["mode"] == "pro"


# ── codex ─────────────────────────────────────────────────────────────────────

class TestCodexFetch:
    def test_returns_none_when_auth_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(codex_q, "_auth_path", lambda: tmp_path / "missing.json")
        assert codex_q.fetch() is None

    def test_returns_error_on_malformed_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        auth = tmp_path / "auth.json"
        auth.write_text("{ bad", encoding="utf-8")
        monkeypatch.setattr(codex_q, "_auth_path", lambda: auth)
        result = codex_q.fetch()
        assert result == {"mode": "error", "error": "~/.codex/auth.json unreadable"}

    def test_returns_api_key_for_apikey_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        auth = tmp_path / "auth.json"
        auth.write_text(json.dumps({"auth_mode": "apikey"}), encoding="utf-8")
        monkeypatch.setattr(codex_q, "_auth_path", lambda: auth)
        assert codex_q.fetch() == {"mode": "api_key"}

    def test_chatgpt_without_token_errors_without_network_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        auth = tmp_path / "auth.json"
        auth.write_text(json.dumps({"auth_mode": "chatgpt"}), encoding="utf-8")
        monkeypatch.setattr(codex_q, "_auth_path", lambda: auth)
        result = codex_q.fetch()
        assert result["mode"] == "chatgpt"
        assert "no token" in result["error"]

    def test_id_token_used_first_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        auth = tmp_path / "auth.json"
        auth.write_text(json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": "ID-TOKEN",
                "access_token": "ACCESS-TOKEN",
                "account_id": "acc-123",
            },
        }), encoding="utf-8")
        monkeypatch.setattr(codex_q, "_auth_path", lambda: auth)

        seen_tokens: list[str] = []
        def _fake_call(token, account_id):
            seen_tokens.append(token)
            return {"plan_type": "plus"}, None
        monkeypatch.setattr(codex_q, "_try_call", _fake_call)

        result = codex_q.fetch()
        assert result["mode"] == "chatgpt"
        # id_token should be tried first; success means we never reach access_token.
        assert seen_tokens == ["ID-TOKEN"]

    def test_falls_back_to_access_token_on_403(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import urllib.error
        auth = tmp_path / "auth.json"
        auth.write_text(json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": "ID-TOKEN",
                "access_token": "ACCESS-TOKEN",
                "account_id": "acc-123",
            },
        }), encoding="utf-8")
        monkeypatch.setattr(codex_q, "_auth_path", lambda: auth)

        seen_tokens: list[str] = []
        def _fake_call(token, account_id):
            seen_tokens.append(token)
            if token == "ID-TOKEN":
                err = urllib.error.HTTPError(
                    "https://chatgpt.com/api/codex/usage",
                    403, "Forbidden", {}, None,
                )
                return None, err
            return {"plan_type": "plus"}, None
        monkeypatch.setattr(codex_q, "_try_call", _fake_call)

        result = codex_q.fetch()
        assert result["mode"] == "chatgpt"
        assert seen_tokens == ["ID-TOKEN", "ACCESS-TOKEN"]
        assert "raw" in result

    def test_both_403_returns_endpoint_deprecated_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """403 from every fetch attempt no longer means "tokens stale" —
        as of 2026-04 OpenAI returns generic HTML 403 for the codex
        usage endpoint regardless of token, signaling that programmatic
        quota access has been deprecated. The error message points
        users to the web settings page instead."""
        import urllib.error
        auth = tmp_path / "auth.json"
        auth.write_text(json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "id_token": "ID-TOKEN",
                "access_token": "ACCESS-TOKEN",
                "account_id": "acc-123",
            },
        }), encoding="utf-8")
        monkeypatch.setattr(codex_q, "_auth_path", lambda: auth)

        def _always_403(token, account_id):
            err = urllib.error.HTTPError(
                "https://chatgpt.com/api/codex/usage",
                403, "Forbidden", {}, None,
            )
            return None, err
        monkeypatch.setattr(codex_q, "_try_call", _always_403)

        result = codex_q.fetch()
        assert result["mode"] == "chatgpt"
        assert "chatgpt.com/codex/settings/usage" in result["error"]
        assert "currently unavailable" in result["error"]


# ── gemini ────────────────────────────────────────────────────────────────────

class TestGeminiFetch:
    def test_returns_none_when_settings_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gemini_q, "_settings_path", lambda: tmp_path / "missing.json"
        )
        assert gemini_q.fetch() is None

    def test_returns_unknown_on_malformed_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text("{ oops", encoding="utf-8")
        monkeypatch.setattr(gemini_q, "_settings_path", lambda: settings)
        assert gemini_q.fetch() == {"auth_type": "unknown"}

    def test_returns_selected_auth_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text(
            json.dumps({"selectedAuthType": "oauth-personal"}), encoding="utf-8"
        )
        monkeypatch.setattr(gemini_q, "_settings_path", lambda: settings)
        assert gemini_q.fetch() == {"auth_type": "oauth-personal"}


# ── hermes ────────────────────────────────────────────────────────────────────


class TestHermesFetch:
    """Aggregate hermes usage from a synthetic ~/.hermes/state.db.

    The fetcher must roll the same row into every window it falls in
    (hour / day / week), exclude older rows once a window's cutoff
    passes, and degrade gracefully when the db is missing or has the
    wrong schema.
    """

    @staticmethod
    def _make_db(path: Path, rows: list[dict]) -> None:
        """Build a minimal sessions-shape db at `path`.

        Only the columns the fetcher selects are present; the real
        Hermes schema has many more, but a forward-compatible fetcher
        must work as long as its required columns exist.
        """
        import sqlite3

        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    started_at REAL NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cache_read_tokens INTEGER DEFAULT 0,
                    cache_write_tokens INTEGER DEFAULT 0,
                    reasoning_tokens INTEGER DEFAULT 0,
                    actual_cost_usd REAL
                )
                """
            )
            conn.executemany(
                "INSERT INTO sessions(id, started_at, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, reasoning_tokens, "
                "actual_cost_usd) VALUES (:id, :started_at, :in, :out, :cr, :cw, "
                ":rs, :cost)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def test_not_installed_when_db_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.quota import hermes as hermes_q

        monkeypatch.setattr(hermes_q, "_db_path", lambda: tmp_path / "no.db")
        assert hermes_q.fetch() == {"mode": "not_installed"}

    def test_aggregates_window_sums(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import time
        from central_mcp.quota import hermes as hermes_q

        now = time.time()
        db = tmp_path / "state.db"
        self._make_db(db, [
            # 30 minutes ago — in all three windows.
            {"id": "a", "started_at": now - 1800,
             "in": 100, "out": 50, "cr": 0, "cw": 0, "rs": 10, "cost": 0.05},
            # 12 hours ago — in day + week, not hour.
            {"id": "b", "started_at": now - 43200,
             "in": 200, "out": 60, "cr": 1000, "cw": 0, "rs": 20, "cost": 0.10},
            # 5 days ago — week only.
            {"id": "c", "started_at": now - 86400 * 5,
             "in": 50, "out": 25, "cr": 0, "cw": 0, "rs": 5, "cost": 0.02},
            # 30 days ago — outside every window.
            {"id": "old", "started_at": now - 86400 * 30,
             "in": 9999, "out": 9999, "cr": 0, "cw": 0, "rs": 0, "cost": 5.0},
        ])
        monkeypatch.setattr(hermes_q, "_db_path", lambda: db)

        out = hermes_q.fetch()
        assert out["mode"] == "local_ledger"
        # Hour window: row 'a' only.
        assert out["hour"]["sessions"] == 1
        assert out["hour"]["input_tokens"] == 100
        assert out["hour"]["output_tokens"] == 50
        assert out["hour"]["total_tokens"] == 150
        assert out["hour"]["cost_usd"] == 0.05
        # Day window: rows 'a' + 'b'.
        assert out["day"]["sessions"] == 2
        assert out["day"]["input_tokens"] == 300
        assert out["day"]["output_tokens"] == 110
        assert out["day"]["cache_read_tokens"] == 1000
        assert out["day"]["cost_usd"] == 0.15
        # Week window: 'a' + 'b' + 'c'.
        assert out["week"]["sessions"] == 3
        assert out["week"]["input_tokens"] == 350
        assert out["week"]["output_tokens"] == 135
        # 30-day-old row must never bleed into any window — strongest
        # signal that the cutoff math is right.
        assert out["week"]["input_tokens"] != 350 + 9999

    def test_handles_null_cost(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`actual_cost_usd` is nullable in the real schema (provider
        didn't report it). The fetcher must coerce NULL → 0.0 instead
        of letting it bubble up through SUM."""
        import time
        from central_mcp.quota import hermes as hermes_q

        now = time.time()
        db = tmp_path / "state.db"
        self._make_db(db, [
            {"id": "x", "started_at": now - 60,
             "in": 1, "out": 1, "cr": 0, "cw": 0, "rs": 0, "cost": None},
        ])
        monkeypatch.setattr(hermes_q, "_db_path", lambda: db)

        out = hermes_q.fetch()
        assert out["hour"]["cost_usd"] == 0.0
        assert out["hour"]["sessions"] == 1

    def test_returns_error_on_corrupt_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.quota import hermes as hermes_q

        bad = tmp_path / "state.db"
        bad.write_bytes(b"this is not a sqlite database")
        monkeypatch.setattr(hermes_q, "_db_path", lambda: bad)

        out = hermes_q.fetch()
        assert out["mode"] == "error"
        assert "error" in out


class TestHermesNormalize:
    """Normalize layer in `quota.__init__` keeps the snapshot shape
    stable across fetcher quirks so downstream renderers don't have
    to branch on every error case."""

    def test_none_becomes_not_installed(self) -> None:
        from central_mcp.quota import _normalize_hermes
        assert _normalize_hermes(None) == {"mode": "not_installed"}

    def test_error_passes_through(self) -> None:
        from central_mcp.quota import _normalize_hermes
        out = _normalize_hermes({"mode": "error", "error": "boom"})
        assert out["mode"] == "error"
        assert out["error"] == "boom"

    def test_local_ledger_includes_three_windows(self) -> None:
        from central_mcp.quota import _normalize_hermes

        ledger = {
            "mode": "local_ledger",
            "hour": {"input_tokens": 1, "sessions": 1},
            "day":  {"input_tokens": 5, "sessions": 3},
            "week": {"input_tokens": 9, "sessions": 7},
        }
        out = _normalize_hermes(ledger)
        assert out["mode"] == "local_ledger"
        assert "note" in out
        assert out["hour"] == ledger["hour"]
        assert out["day"]  == ledger["day"]
        assert out["week"] == ledger["week"]


def test_snapshot_includes_hermes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The top-level `snapshot()` must surface hermes alongside the
    other providers so callers iterating over the dict see it without
    a special case."""
    from central_mcp import quota
    from central_mcp.quota import hermes as hermes_q

    quota._reset_cache_for_tests()
    # Hermes-side stub: a simple "not_installed" return so we don't
    # depend on an actual ~/.hermes/state.db on the test machine.
    monkeypatch.setattr(hermes_q, "fetch", lambda: {"mode": "not_installed"})

    snap = quota.snapshot(force=True)
    assert "hermes" in snap
    assert snap["hermes"]["mode"] == "not_installed"
