"""Tests for the pre-rendered token_usage summary (`quota.render`)."""

from __future__ import annotations

import pytest

from central_mcp.quota import render


# ── helpers ───────────────────────────────────────────────────────────────────

class TestColorEmoji:
    def test_green_below_50(self) -> None:
        assert render._color_emoji(0) == "🟢"
        assert render._color_emoji(49.9) == "🟢"

    def test_yellow_50_to_90(self) -> None:
        assert render._color_emoji(50) == "🟡"
        assert render._color_emoji(73) == "🟡"
        assert render._color_emoji(89.9) == "🟡"

    def test_red_at_or_above_90(self) -> None:
        assert render._color_emoji(90) == "🔴"
        assert render._color_emoji(100) == "🔴"
        assert render._color_emoji(150) == "🔴"


class TestBar:
    def test_zero_is_all_empty(self) -> None:
        assert render._bar(0) == "░" * 20

    def test_full_is_all_filled(self) -> None:
        assert render._bar(100) == "█" * 20

    def test_clamps_below_zero(self) -> None:
        assert render._bar(-50) == "░" * 20

    def test_clamps_above_hundred(self) -> None:
        assert render._bar(200) == "█" * 20

    def test_partial(self) -> None:
        # 50% of 20 = 10 filled cells
        bar = render._bar(50)
        assert bar.count("█") == 10
        assert bar.count("░") == 10
        assert len(bar) == 20


class TestFmtTokens:
    def test_under_thousand(self) -> None:
        assert render._fmt_tokens(540) == "540"
        assert render._fmt_tokens(0) == "0"

    def test_thousands(self) -> None:
        assert render._fmt_tokens(7_000) == "7.0K"
        assert render._fmt_tokens(260_000) == "260.0K"

    def test_millions(self) -> None:
        assert render._fmt_tokens(8_970_000) == "8.97M"
        assert render._fmt_tokens(53_555_198) == "53.56M"


# ── render_summary ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_result() -> dict:
    return {
        "period": "today",
        "timezone": "Asia/Seoul",
        "breakdown": {
            "ORCHESTRATOR": {"total": 8_970_000},
            "tui-4-everything": {"total": 53_560_000},
            "retro-hog": {"total": 10_560_000},
            "andineering": {"total": 260_000},
            "central-mcp": {"total": 7_000},
        },
        "total": {"total": 73_357_000},
        "quota": {
            "claude": {
                "mode": "pro",
                "five_hour": {"used_pct": 100, "resets_in": "1h52m"},
                "seven_day": {"used_pct": 100, "resets_in": "1d12h"},
            },
            "codex": {
                "mode": "chatgpt",
                "plan": "plus",
                "primary":   {"window": "5h", "used_pct": 18, "resets_in": "4h"},
                "secondary": {"window": "1d", "used_pct": 12, "resets_in": "22h"},
            },
            "gemini": {"mode": "auth_only", "auth_type": "oauth-personal"},
        },
    }


class TestRenderSummary:
    def test_includes_title_with_period_and_tz(self, sample_result) -> None:
        out = render.render_summary(sample_result)
        assert out.startswith("**Token Usage — today (Asia/Seoul)**")

    def test_wraps_in_text_code_fence(self, sample_result) -> None:
        out = render.render_summary(sample_result)
        # Opening fence + closing fence both present.
        assert "```text" in out
        assert out.rstrip().endswith("```")

    def test_quota_section_present(self, sample_result) -> None:
        out = render.render_summary(sample_result)
        assert "SUBSCRIPTION QUOTA" in out
        # Both Claude windows show up.
        assert "5h" in out
        assert "7d" in out
        # Both Codex windows.
        assert "1d" in out

    def test_breakdown_section_present(self, sample_result) -> None:
        out = render.render_summary(sample_result)
        assert "PROJECT BREAKDOWN" in out
        # Total formatted compactly.
        assert "73.36M" in out
        assert "ORCHESTRATOR" in out
        assert "tui-4-everything" in out

    def test_color_thresholds_applied_per_user_spec(
        self, sample_result
    ) -> None:
        """Color emoji per the spec: 🟢 < 50%, 🟡 50–89%, 🔴 ≥ 90%."""
        out = render.render_summary(sample_result)
        # Claude is at 100% → 🔴 should appear at least twice (5h + 7d).
        assert out.count("🔴") >= 2
        # tui-4-everything is 73% of total → 🟡.
        # Codex primary 18% / secondary 12% → 🟢.
        assert "🟢" in out and "🟡" in out

    def test_orchestrator_row_first(self, sample_result) -> None:
        """ORCHESTRATOR row appears before any other project row."""
        out = render.render_summary(sample_result)
        orch_pos = out.find("ORCHESTRATOR")
        tui_pos  = out.find("tui-4-everything")
        assert 0 < orch_pos < tui_pos

    def test_empty_result_renders_no_data_message(self) -> None:
        out = render.render_summary({
            "period": "today",
            "timezone": "UTC",
            "breakdown": {},
            "total": {"total": 0},
        })
        assert "(no data for this period)" in out

    def test_quota_only_no_breakdown(self) -> None:
        """Quota present but no token activity yet — quota section
        renders, breakdown is omitted."""
        out = render.render_summary({
            "period": "today",
            "timezone": "UTC",
            "breakdown": {},
            "total": {"total": 0},
            "quota": {
                "claude": {"mode": "api_key"},
            },
        })
        assert "SUBSCRIPTION QUOTA" in out
        assert "PROJECT BREAKDOWN" not in out
        assert "no subscription quota" in out

    def test_breakdown_only_no_quota(self) -> None:
        """Breakdown present but no quota info (e.g. include_quota=False)."""
        out = render.render_summary({
            "period": "today",
            "timezone": "UTC",
            "breakdown": {
                "p1": {"total": 100},
            },
            "total": {"total": 100},
        })
        assert "PROJECT BREAKDOWN" in out
        assert "SUBSCRIPTION QUOTA" not in out

    def test_codex_api_key_mode(self) -> None:
        out = render.render_summary({
            "period": "today",
            "timezone": "UTC",
            "breakdown": {},
            "total": {"total": 0},
            "quota": {
                "codex": {"mode": "api_key"},
            },
        })
        assert "codex" in out
        assert "API Key" in out
        assert "no subscription quota" in out

    def test_gemini_auth_only(self) -> None:
        out = render.render_summary({
            "period": "today",
            "timezone": "UTC",
            "breakdown": {},
            "total": {"total": 0},
            "quota": {
                "gemini": {"mode": "auth_only", "auth_type": "oauth-personal"},
            },
        })
        assert "gemini" in out
        assert "oauth-personal" in out
        assert "no quota API available" in out

    def test_not_installed_modes_silent(self) -> None:
        """Agents that aren't installed don't add noise to the output."""
        out = render.render_summary({
            "period": "today",
            "timezone": "UTC",
            "breakdown": {},
            "total": {"total": 0},
            "quota": {
                "claude": {"mode": "pro",
                           "five_hour": {"used_pct": 10, "resets_in": "1h"},
                           "seven_day": {"used_pct": 5, "resets_in": "5d"}},
                "codex": {"mode": "not_installed"},
                "gemini": {"mode": "not_installed"},
            },
        })
        assert "claude" in out
        assert "codex" not in out
        assert "gemini" not in out

    def test_zero_total_skips_breakdown(self) -> None:
        """Even with breakdown entries, zero grand-total → no breakdown
        block (avoid divide-by-zero in share calc)."""
        out = render.render_summary({
            "period": "today",
            "timezone": "UTC",
            "breakdown": {"p1": {"total": 0}},
            "total": {"total": 0},
        })
        assert "PROJECT BREAKDOWN" not in out
