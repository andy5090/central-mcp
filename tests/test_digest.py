"""Tests for the portfolio digest and the list_dispatches failure cursor.

Classification and rendering are tested against synthetic pulses
(monkeypatched `pulse_many`) so window edges are exact; one end-to-end
case runs the real pulse path over a real git repo.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from central_mcp import digest, dispatches_db, events, registry, server

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

HOUR = 3600.0
DAY = 86400.0


def _proj(name: str) -> registry.Project:
    return registry.Project(name=name, path=f"/tmp/{name}", agent="hermes")


def _pulse(
    name: str,
    *,
    age: float | None,
    commits: list[dict] | None = None,
    recent: list[dict] | None = None,
    stale: list[dict] | None = None,
    in_flight: list[dict] | None = None,
    dirty: int = 0,
    branch: str = "main",
    ok: bool = True,
    error: str | None = None,
) -> dict:
    if not ok:
        return {"ok": False, "project": name, "error": error or "boom"}
    return {
        "ok": True,
        "project": name,
        "agent": "hermes",
        "last_activity_age_sec": age,
        "git": {
            "available": True,
            "branch": branch,
            "detached": False,
            "dirty": {"total": dirty},
            "recent_commits": commits or [],
        },
        "dispatches": {
            "in_flight": in_flight or [],
            "stale": stale or [],
            "recent": recent or [],
            "counts": {},
        },
        "sessions": {"available": False},
        "pull_requests": {"available": False},
    }


def _install(monkeypatch: pytest.MonkeyPatch, pulses: list[dict]) -> None:
    monkeypatch.setattr(digest.pulse_mod, "pulse_many", lambda projects, **kw: pulses)


class TestClassification:
    def test_window_edge_splits_active_from_quiet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [
            _pulse("fresh", age=23 * HOUR),
            _pulse("stale-ish", age=25 * HOUR),
        ])
        d = digest.build([_proj("fresh"), _proj("stale-ish")], since_hours=24)
        assert [a["project"] for a in d["active"]] == ["fresh"]
        assert [q["project"] for q in d["quiet"]] == ["stale-ish"]

    def test_active_counts_only_in_window_commits_and_dispatches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [
            _pulse(
                "p",
                age=1 * HOUR,
                commits=[
                    {"age_sec": 1 * HOUR, "subject": "new work"},
                    {"age_sec": 30 * HOUR, "subject": "old work"},
                ],
                recent=[
                    {"age_sec": 2 * HOUR, "ok": True, "event": "complete"},
                    {"age_sec": 3 * HOUR, "ok": False, "event": "complete"},
                    {"age_sec": 40 * HOUR, "ok": False, "event": "complete"},
                ],
            ),
        ])
        d = digest.build([_proj("p")], since_hours=24)
        a = d["active"][0]
        assert a["commits"] == 1
        assert a["latest_subject"] == "new work"
        assert a["dispatch_ok"] == 1
        assert a["dispatch_failed"] == 1          # the 40h-old failure is outside
        failed = [w for w in d["warnings"] if w["kind"] == "dispatch_failed"]
        assert len(failed) == 1

    def test_cancelled_is_not_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, [
            _pulse("p", age=HOUR,
                   recent=[{"age_sec": HOUR, "ok": False, "event": "cancelled"}]),
        ])
        d = digest.build([_proj("p")], since_hours=24)
        assert d["active"][0]["dispatch_failed"] == 0
        assert not [w for w in d["warnings"] if w["kind"] == "dispatch_failed"]

    def test_active_sorted_most_recent_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [
            _pulse("older", age=5 * HOUR),
            _pulse("newer", age=1 * HOUR),
        ])
        d = digest.build([_proj("older"), _proj("newer")], since_hours=24)
        assert [a["project"] for a in d["active"]] == ["newer", "older"]

    def test_quiet_sorted_longest_idle_first_unknown_last(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [
            _pulse("idle-30d", age=30 * DAY),
            _pulse("idle-100d", age=100 * DAY),
            _pulse("never", age=None),
        ])
        d = digest.build([_proj("a"), _proj("b"), _proj("c")], since_hours=24)
        assert [q["project"] for q in d["quiet"]] == ["idle-100d", "idle-30d", "never"]


class TestWarnings:
    def test_stale_dispatch_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, [
            _pulse("p", age=100 * DAY, stale=[{"elapsed_sec": 92 * DAY}]),
        ])
        d = digest.build([_proj("p")], since_hours=24)
        w = [w for w in d["warnings"] if w["kind"] == "stale_dispatch"]
        assert len(w) == 1
        assert "never finalized" in w[0]["detail"]

    def test_quiet_with_uncommitted_work_warns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [
            _pulse("dropped", age=10 * DAY, dirty=3),
            _pulse("clean-idle", age=10 * DAY, dirty=0),
            _pulse("recent-dirty", age=2 * DAY, dirty=5),   # under quiet_days
        ])
        d = digest.build([_proj("a"), _proj("b"), _proj("c")],
                         since_hours=24, quiet_days=7)
        w = [w for w in d["warnings"] if w["kind"] == "uncommitted_and_quiet"]
        assert [x["project"] for x in w] == ["dropped"]

    def test_failed_pulse_becomes_warning_not_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(monkeypatch, [
            _pulse("ok-one", age=HOUR),
            _pulse("bad", age=None, ok=False, error="kaboom"),
        ])
        d = digest.build([_proj("a"), _proj("b")], since_hours=24)
        assert d["ok"] is True
        w = [w for w in d["warnings"] if w["kind"] == "pulse_failed"]
        assert w and "kaboom" in w[0]["detail"]


class TestQuotaFlatten:
    def test_windows_flattened_with_labels(self) -> None:
        snap = {
            "claude": {
                "mode": "pro",
                "five_hour": {"used_pct": 34.0, "resets_in": "2h"},
                "seven_day": {"used_pct": 12.0, "resets_in": "5d"},
            },
            "codex": {
                "mode": "chatgpt",
                "primary": {"used_pct": 61.0, "resets_in": "1h"},
                "secondary": {},                      # no data → skipped
            },
        }
        windows = digest._quota_windows(snap)
        assert [(w["agent"], w["window"], w["used_pct"]) for w in windows] == [
            ("claude", "five_hour", 34.0),
            ("claude", "seven_day", 12.0),
            ("codex", "primary", 61.0),
        ]

    def test_errored_agents_yield_nothing(self) -> None:
        snap = {
            "claude": {"mode": "pro", "error": "HTTP Error 401"},
            "codex": {"mode": "error", "error": "down"},
        }
        assert digest._quota_windows(snap) == []


class TestRender:
    def test_render_full_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, [
            _pulse(
                "busy", age=HOUR, dirty=6, branch="staging",
                commits=[{"age_sec": HOUR, "subject": "feat: thing"}],
                recent=[{"age_sec": HOUR, "ok": True, "event": "complete"}],
            ),
            _pulse("idle", age=40 * DAY),
        ])
        d = digest.build(
            [_proj("busy"), _proj("idle")],
            workspace_label="default", since_hours=24,
            quota={"claude": {"mode": "pro",
                              "five_hour": {"used_pct": 91.0},
                              "seven_day": {"used_pct": 40.0}},
                   "codex": {}},
        )
        text = digest.render(d)
        assert "Portfolio digest" in text
        assert "**busy** `staging`" in text
        assert "1 commit(s)" in text
        assert "dispatches ✅1/❌0" in text
        assert "6 uncommitted" in text
        assert "latest: feat: thing" in text
        assert "**Quiet** — 1 project(s) (longest: idle, 40d ago)" in text
        assert "claude 5h 🔴91%" in text
        assert "claude 7d 🟢40%" in text

    def test_render_commit_cap_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        commits = [{"age_sec": HOUR, "subject": f"c{i}"} for i in range(10)]
        _install(monkeypatch, [_pulse("p", age=HOUR, commits=commits)])
        d = digest.build([_proj("p")], since_hours=24)
        assert "10+ commit(s)" in digest.render(d)

    def test_render_no_activity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, [_pulse("p", age=40 * DAY)])
        text = digest.render(digest.build([_proj("p")], since_hours=24))
        assert "No project activity in this window." in text

    def test_render_empty_portfolio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, [])
        text = digest.render(digest.build([], since_hours=24))
        assert "0 project(s)" in text


@needs_git
class TestEndToEnd:
    def test_real_pulse_path(self, fake_home: Path, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=repo,
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo,
                       check=True, capture_output=True)
        (repo / "f.txt").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=repo, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "fresh commit"], cwd=repo,
                       check=True, capture_output=True)
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        events.log_event("proj", "d1", "start", prompt="p", agent="hermes")
        events.log_event("proj", "d1", "error", error="exploded")

        d = digest.build(registry.load_registry(), since_hours=24)
        assert [a["project"] for a in d["active"]] == ["proj"]
        assert d["active"][0]["commits"] == 1
        failed = [w for w in d["warnings"] if w["kind"] == "dispatch_failed"]
        assert failed and "exploded" in failed[0]["detail"]
        text = digest.render(d)
        assert "fresh commit" in text

    def test_mcp_tool_returns_verbatim_markdown(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                       capture_output=True)
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        r = server.portfolio_digest(include_quota=False)
        assert r["ok"] is True
        assert r["quota"] is None
        assert "Portfolio digest" in r["digest_markdown"]


class TestListDispatchesCursor:
    def _seed(self, *, ok: bool, status: str = "complete",
              did: str = "d1") -> None:
        dispatches_db.upsert_started({
            "id": did, "project": "proj", "agent": "hermes",
            "status": "running", "started": time.time() - 60, "prompt": "p",
        })
        dispatches_db.upsert_finished(did, status, {
            "ok": ok, "duration_sec": 60.0, "output": "", "stderr": "",
        })

    def test_rows_carry_ok_and_finished_at(self, fake_home: Path) -> None:
        self._seed(ok=True)
        rows = server.list_dispatches()
        assert rows[0]["ok"] is True
        assert rows[0]["finished_at"] is not None

    def test_failed_alias_matches_error_and_not_ok_complete(
        self, fake_home: Path
    ) -> None:
        self._seed(ok=False, status="complete", did="bad-complete")
        self._seed(ok=False, status="error", did="bad-error")
        self._seed(ok=True, status="complete", did="fine")
        self._seed(ok=False, status="cancelled", did="stopped")
        failed = {r["dispatch_id"] for r in server.list_dispatches(status="failed")}
        assert failed == {"bad-complete", "bad-error"}

    def test_exact_status_filter(self, fake_home: Path) -> None:
        self._seed(ok=False, status="error", did="e1")
        self._seed(ok=True, status="complete", did="c1")
        rows = server.list_dispatches(status="error")
        assert [r["dispatch_id"] for r in rows] == ["e1"]

    def test_since_is_strictly_greater(self, fake_home: Path) -> None:
        self._seed(ok=False, status="error", did="old")
        watermark = server.list_dispatches(status="failed")[0]["finished_at"]
        # Same watermark → nothing new; that exact row never re-alerts.
        assert server.list_dispatches(status="failed", since=watermark) == []
        self._seed(ok=False, status="error", did="new")
        fresh = server.list_dispatches(status="failed", since=watermark)
        assert [r["dispatch_id"] for r in fresh] == ["new"]

    def test_since_accepts_z_suffix(self, fake_home: Path) -> None:
        self._seed(ok=False, status="error")
        rows = server.list_dispatches(status="failed",
                                      since="2000-01-01T00:00:00Z")
        assert len(rows) == 1

    def test_running_rows_pass_the_since_filter(self, fake_home: Path) -> None:
        dispatches_db.upsert_started({
            "id": "live", "project": "proj", "agent": "hermes",
            "status": "running", "started": time.time(), "prompt": "p",
        })
        rows = server.list_dispatches(since="2999-01-01T00:00:00Z")
        assert [r["dispatch_id"] for r in rows] == ["live"]

    def test_malformed_since_raises(self, fake_home: Path) -> None:
        with pytest.raises(ValueError, match="ISO 8601"):
            server.list_dispatches(since="yesterday-ish")
