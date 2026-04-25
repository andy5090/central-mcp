"""Tests for `central_mcp.quota.snapshot()` — the normalized per-agent
quota payload that `token_usage` returns alongside its breakdown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from central_mcp import quota


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    quota._reset_cache_for_tests()


# ── individual normalizers ────────────────────────────────────────────────────

class TestNormalizeClaude:
    def test_none_means_not_installed(self) -> None:
        assert quota._normalize_claude(None) == {"mode": "not_installed"}

    def test_api_key_mode(self) -> None:
        out = quota._normalize_claude({"mode": "api_key"})
        assert out["mode"] == "api_key"
        assert "no subscription quota" in out["note"]

    def test_error_mode(self) -> None:
        out = quota._normalize_claude({"mode": "error", "error": "boom"})
        assert out == {"mode": "error", "error": "boom"}

    def test_pro_with_error_preserves_error(self) -> None:
        out = quota._normalize_claude({"mode": "pro", "error": "rate limited"})
        assert out["mode"] == "pro"
        assert out["error"] == "rate limited"
        assert "five_hour" not in out

    def test_pro_with_raw_extracts_windows(self) -> None:
        future_5h = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        future_7d = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        out = quota._normalize_claude({
            "mode": "pro",
            "raw": {
                "five_hour": {"utilization": 0.42, "resets_at": future_5h},
                "seven_day": {"utilization": 0.85, "resets_at": future_7d},
            },
        })
        assert out["mode"] == "pro"
        assert out["five_hour"]["used_pct"] == 42.0
        assert out["seven_day"]["used_pct"] == 85.0
        # Reset-in is "Xh..m" or "Yd..h" — just sanity check.
        assert out["five_hour"]["resets_in"].endswith("m") or "h" in out["five_hour"]["resets_in"]
        assert "d" in out["seven_day"]["resets_in"]


class TestNormalizeCodex:
    def test_none_means_not_installed(self) -> None:
        assert quota._normalize_codex(None) == {"mode": "not_installed"}

    def test_api_key_mode(self) -> None:
        out = quota._normalize_codex({"mode": "api_key"})
        assert out["mode"] == "api_key"

    def test_chatgpt_with_rate_limit(self) -> None:
        out = quota._normalize_codex({
            "mode": "chatgpt",
            "raw": {
                "plan_type": "plus",
                "rate_limit": {
                    "primary_window":   {"used_percent": 25, "limit_window_seconds": 18000,
                                         "reset_after_seconds": 3600},
                    "secondary_window": {"used_percent": 60, "limit_window_seconds": 86400,
                                         "reset_after_seconds": 12 * 3600},
                },
            },
        })
        assert out["mode"] == "chatgpt"
        assert out["plan"] == "plus"
        assert out["primary"]["window"] == "5h"
        assert out["primary"]["used_pct"] == 25.0
        assert out["secondary"]["window"] == "1d"
        assert out["secondary"]["used_pct"] == 60.0


class TestNormalizeGemini:
    def test_none_means_not_installed(self) -> None:
        assert quota._normalize_gemini(None) == {"mode": "not_installed"}

    def test_auth_only_passthrough(self) -> None:
        out = quota._normalize_gemini({"auth_type": "oauth-personal"})
        assert out["mode"] == "auth_only"
        assert out["auth_type"] == "oauth-personal"


# ── snapshot() integration ────────────────────────────────────────────────────

class TestSnapshot:
    def test_includes_all_three_agents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(quota._claude, "fetch", lambda: {"mode": "api_key"})
        monkeypatch.setattr(quota._codex,  "fetch", lambda: None)
        monkeypatch.setattr(quota._gemini, "fetch",
                            lambda: {"auth_type": "oauth-personal"})
        snap = quota.snapshot(force=True)
        assert snap["claude"]["mode"] == "api_key"
        assert snap["codex"]["mode"] == "not_installed"
        assert snap["gemini"]["mode"] == "auth_only"
        assert "fetched_at" in snap
        assert snap["cached"] is False

    def test_fetcher_exception_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> Any:
            raise RuntimeError("network down")
        monkeypatch.setattr(quota._claude, "fetch", _boom)
        monkeypatch.setattr(quota._codex,  "fetch", lambda: {"mode": "api_key"})
        monkeypatch.setattr(quota._gemini, "fetch", lambda: None)
        snap = quota.snapshot(force=True)
        assert snap["claude"]["mode"] == "error"
        assert "network down" in snap["claude"]["error"]
        # Other agents still resolved.
        assert snap["codex"]["mode"] == "api_key"
        assert snap["gemini"]["mode"] == "not_installed"

    def test_cache_returns_same_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}
        def _count() -> dict[str, Any]:
            calls["n"] += 1
            return {"mode": "api_key"}
        monkeypatch.setattr(quota._claude, "fetch", _count)
        monkeypatch.setattr(quota._codex,  "fetch", lambda: None)
        monkeypatch.setattr(quota._gemini, "fetch", lambda: None)

        first  = quota.snapshot()
        second = quota.snapshot()
        assert calls["n"] == 1, "second call should be served from cache"
        assert first["cached"] is False
        assert second["cached"] is True

    def test_force_bypasses_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}
        def _count() -> dict[str, Any]:
            calls["n"] += 1
            return {"mode": "api_key"}
        monkeypatch.setattr(quota._claude, "fetch", _count)
        monkeypatch.setattr(quota._codex,  "fetch", lambda: None)
        monkeypatch.setattr(quota._gemini, "fetch", lambda: None)

        quota.snapshot()
        quota.snapshot(force=True)
        assert calls["n"] == 2, "force=True must skip the cache"


# ── helpers ───────────────────────────────────────────────────────────────────

class TestFormatters:
    def test_fmt_reset_secs_zero_or_negative(self) -> None:
        assert quota._fmt_reset_secs(0) == "now"
        assert quota._fmt_reset_secs(-10) == "now"

    def test_fmt_reset_secs_minutes(self) -> None:
        assert quota._fmt_reset_secs(45 * 60) == "45m"

    def test_fmt_reset_secs_hours(self) -> None:
        assert quota._fmt_reset_secs(2 * 3600 + 30 * 60) == "2h30m"

    def test_fmt_reset_secs_days(self) -> None:
        assert quota._fmt_reset_secs(2 * 86400 + 3 * 3600) == "2d03h"

    def test_safe_pct_clamps(self) -> None:
        assert quota._safe_pct(-5) == 0.0
        assert quota._safe_pct(150) == 100.0
        assert quota._safe_pct("not a number") == 0.0
        assert quota._safe_pct(42.5) == 42.5

    def test_window_label(self) -> None:
        assert quota._window_label(3600, "?") == "1h"
        assert quota._window_label(5 * 3600, "?") == "5h"
        assert quota._window_label(86400, "?") == "1d"
        assert quota._window_label(None, "fallback") == "fallback"
