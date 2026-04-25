"""Tests for the `token_usage` MCP tool and `tokens_db.aggregate()`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from central_mcp import config as _cfg
from central_mcp import quota, server, tokens_db
from central_mcp import registry


def _utc_now_iso(delta_days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat(
        timespec="milliseconds"
    )


@pytest.fixture
def seed(fake_home: Path):
    _cfg.set_user_timezone("UTC")
    tokens_db.record(ts=_utc_now_iso(), project="p1", agent="claude",
                     source="dispatch", dispatch_id="d1",
                     input_tokens=100, output_tokens=50, total_tokens=150)
    tokens_db.record(ts=_utc_now_iso(), project="p1", agent="codex",
                     source="dispatch", dispatch_id="d2", total_tokens=200)
    tokens_db.record(ts=_utc_now_iso(), project="p2", agent="claude",
                     source="orchestrator", session_id="s1", request_id="r1",
                     input_tokens=1000, output_tokens=200, total_tokens=1200)
    tokens_db.record(ts=_utc_now_iso(delta_days=-3), project="p2", agent="claude",
                     source="dispatch", dispatch_id="d3", total_tokens=999)
    return fake_home


class TestAggregate:
    def test_today_period_groups_by_project_by_default(self, seed: Path) -> None:
        r = tokens_db.aggregate(period="today", tz_str="UTC")
        assert r["breakdown"]["p1"]["dispatch"] == 350
        assert r["breakdown"]["p2"]["orchestrator"] == 1200
        # 3-day-old record is outside today.
        assert "p2" in r["breakdown"]
        assert r["breakdown"]["p2"].get("dispatch", 0) == 0
        assert r["total"]["total"] == 350 + 1200

    def test_week_period_includes_older_records(self, seed: Path) -> None:
        r = tokens_db.aggregate(period="week", tz_str="UTC")
        assert r["breakdown"]["p2"]["dispatch"] == 999
        assert r["breakdown"]["p2"]["orchestrator"] == 1200

    def test_all_period_no_bounds(self, seed: Path) -> None:
        r = tokens_db.aggregate(period="all", tz_str="UTC")
        assert r["window"]["start"] is None
        assert r["window"]["end"] is None
        assert r["total"]["total"] == 350 + 1200 + 999

    def test_group_by_agent(self, seed: Path) -> None:
        r = tokens_db.aggregate(period="all", tz_str="UTC", group_by="agent")
        assert "claude" in r["breakdown"]
        assert "codex" in r["breakdown"]
        assert r["breakdown"]["codex"]["total"] == 200

    def test_group_by_source(self, seed: Path) -> None:
        r = tokens_db.aggregate(period="today", tz_str="UTC", group_by="source")
        assert "dispatch" in r["breakdown"]
        assert "orchestrator" in r["breakdown"]
        assert r["breakdown"]["orchestrator"]["orchestrator"] == 1200

    def test_project_filter(self, seed: Path) -> None:
        r = tokens_db.aggregate(period="all", tz_str="UTC",
                                project_filter={"p1"})
        assert set(r["breakdown"].keys()) == {"p1"}
        assert r["total"]["total"] == 350

    def test_empty_filter_returns_no_rows(self, seed: Path) -> None:
        r = tokens_db.aggregate(period="all", tz_str="UTC", project_filter=set())
        assert r["breakdown"] == {}
        assert r["total"]["total"] == 0


class TestTokenUsageTool:
    def test_today_default(self, seed: Path) -> None:
        r = server.token_usage()
        assert r["ok"] is True
        assert r["period"] == "today"
        assert r["group_by"] == "project"
        assert r["breakdown"]["p1"]["total"] == 350

    def test_rejects_bad_period(self, fake_home: Path) -> None:
        r = server.token_usage(period="bogus")
        assert r["ok"] is False
        assert "bogus" in r["error"]

    def test_rejects_bad_group_by(self, fake_home: Path) -> None:
        r = server.token_usage(group_by="nope")
        assert r["ok"] is False

    def test_project_filter_wins_over_workspace(self, seed: Path) -> None:
        r = server.token_usage(period="all", project="p1", workspace="default")
        assert set(r["breakdown"].keys()) == {"p1"}

    def test_workspace_filter(self, seed: Path) -> None:
        # Seed the registry with p1/p2 and put p2 in "w1".
        registry.add_project("p1", "/tmp/p1")
        registry.add_project("p2", "/tmp/p2")
        registry.add_workspace("w1")
        registry.add_to_workspace("p2", "w1")
        r = server.token_usage(period="all", workspace="w1")
        assert set(r["breakdown"].keys()) == {"p2"}

    def test_orchestration_history_no_longer_returns_tokens(
        self, seed: Path
    ) -> None:
        hist = server.orchestration_history()
        for entry in hist.get("per_project", {}).values():
            assert "tokens_today" not in entry
            assert "tokens_week" not in entry
            assert "tokens_total" not in entry


class TestTokenUsageQuotaInclusion:
    """`token_usage` must include the per-agent quota snapshot by default."""

    def _stub_fetchers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(quota._claude, "fetch", lambda: {"mode": "api_key"})
        monkeypatch.setattr(quota._codex,  "fetch", lambda: None)
        monkeypatch.setattr(quota._gemini, "fetch", lambda: None)
        quota._reset_cache_for_tests()

    def test_quota_present_by_default(
        self, seed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_fetchers(monkeypatch)
        r = server.token_usage()
        assert "quota" in r
        assert r["quota"]["claude"]["mode"] == "api_key"
        assert r["quota"]["codex"]["mode"]  == "not_installed"
        assert r["quota"]["gemini"]["mode"] == "not_installed"
        assert "fetched_at" in r["quota"]

    def test_include_quota_false_omits_field(
        self, seed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_fetchers(monkeypatch)
        r = server.token_usage(include_quota=False)
        assert "quota" not in r

    def test_quota_failure_does_not_break_tool(
        self, seed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Make the snapshot itself blow up — token tally must still come back.
        def _explode(**_kw):
            raise RuntimeError("snapshot failure")
        monkeypatch.setattr(quota, "snapshot", _explode)
        r = server.token_usage()
        assert r["ok"] is True
        assert "breakdown" in r
        assert "error" in r["quota"]
