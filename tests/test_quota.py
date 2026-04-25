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

    def test_both_403_returns_helpful_error(
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

        def _always_403(token, account_id):
            err = urllib.error.HTTPError(
                "https://chatgpt.com/api/codex/usage",
                403, "Forbidden", {}, None,
            )
            return None, err
        monkeypatch.setattr(codex_q, "_try_call", _always_403)

        result = codex_q.fetch()
        assert result["mode"] == "chatgpt"
        assert "codex login" in result["error"]


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
