"""Tests for `central_mcp.pulse` — the stateless project-state aggregator.

Git assertions run against real repositories created in tmp_path: the
whole point of the module is reading what git actually reports, so
mocking the porcelain would test our fixture rather than our parser.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from central_mcp import dispatches_db, events, pulse, registry
from central_mcp.adapters.base import Adapter, SessionInfo

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _make_repo(path: Path, *, commits: int = 1) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")
    for i in range(commits):
        (path / f"file{i}.txt").write_text(f"content {i}\n")
        _git(path, "add", ".")
        _git(path, "commit", "-m", f"commit {i}")
    return path


# ---------- formatting helpers ----------

class TestFormatting:
    def test_humanize_age_units(self) -> None:
        assert pulse.humanize_age(None) == "unknown"
        assert pulse.humanize_age(10) == "just now"
        assert pulse.humanize_age(600) == "10m ago"
        assert pulse.humanize_age(7200) == "2h ago"
        assert pulse.humanize_age(3 * 86400) == "3d ago"
        assert pulse.humanize_age(90 * 86400) == "90d ago"

    def test_humanize_duration_has_no_ago_suffix(self) -> None:
        assert pulse.humanize_duration(30) == "30s"
        assert pulse.humanize_duration(600) == "10m"
        assert pulse.humanize_duration(7200) == "2h"
        assert pulse.humanize_duration(92 * 86400) == "92d"
        assert "ago" not in pulse.humanize_duration(92 * 86400)

    def test_oneline_collapses_newlines(self) -> None:
        """Regression: multi-paragraph prompts used to shred list rendering."""
        text = "line one\n\nline two\twith\ttabs\n   padded   "
        assert pulse._oneline(text) == "line one line two with tabs padded"
        assert "\n" not in pulse._oneline(text)

    def test_oneline_truncates_with_ellipsis(self) -> None:
        out = pulse._oneline("x" * 200, 20)
        assert len(out) == 20
        assert out.endswith("…")

    def test_latest_picks_most_recent_and_ignores_junk(self) -> None:
        assert pulse._latest(
            None, "not-a-date", "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"
        ) == "2026-06-01T00:00:00.000+00:00"
        assert pulse._latest(None, "nonsense") is None

    def test_latest_compares_instants_across_offsets(self) -> None:
        """09:00+09:00 is earlier than 01:00Z, despite sorting later as text."""
        assert pulse._latest(
            "2026-07-26T09:00:00+09:00",   # == 00:00Z
            "2026-07-26T01:00:00+00:00",
        ) == "2026-07-26T01:00:00.000+00:00"


# ---------- git ----------

@needs_git
class TestGitSnapshot:
    def test_clean_repo(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo", commits=2)
        snap = pulse.git_snapshot(repo)
        assert snap["available"] is True
        assert snap["branch"] == "main"
        assert snap["detached"] is False
        assert snap["dirty"]["total"] == 0
        assert len(snap["recent_commits"]) == 2
        assert snap["head"]["subject"] == "commit 1"
        assert snap["head"]["author"] == "Test User"

    def test_commit_limit_is_honored(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo", commits=5)
        assert len(pulse.git_snapshot(repo, commits=2)["recent_commits"]) == 2
        assert pulse.git_snapshot(repo, commits=0)["recent_commits"] == []

    def test_dirty_states_are_classified(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        (repo / "file0.txt").write_text("modified\n")     # unstaged
        (repo / "staged.txt").write_text("new\n")
        _git(repo, "add", "staged.txt")                   # staged
        (repo / "untracked.txt").write_text("nope\n")     # untracked

        dirty = pulse.git_snapshot(repo)["dirty"]
        assert dirty["unstaged"] == 1
        assert dirty["staged"] == 1
        assert dirty["untracked"] == 1
        assert dirty["total"] == 3
        assert any(f.startswith("M ") for f in dirty["files"])
        assert any(f.startswith("? ") for f in dirty["files"])

    def test_file_sample_is_bounded_and_flagged(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        for i in range(8):
            (repo / f"extra{i}.txt").write_text("x\n")
        dirty = pulse.git_snapshot(repo, max_files=3)["dirty"]
        assert dirty["total"] == 8
        assert len(dirty["files"]) == 3
        assert dirty["truncated"] is True

    def test_staged_and_unstaged_same_file_counts_both(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        (repo / "file0.txt").write_text("staged change\n")
        _git(repo, "add", "file0.txt")
        (repo / "file0.txt").write_text("and then more\n")

        dirty = pulse.git_snapshot(repo)["dirty"]
        assert dirty["staged"] == 1
        assert dirty["unstaged"] == 1
        assert dirty["total"] == 1          # one file, two states
        assert dirty["files"] == ["SM file0.txt"]

    def test_upstream_ahead_behind(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin.git"
        origin.mkdir()
        _git(origin, "init", "--bare", "-b", "main")
        source = _make_repo(tmp_path / "source", commits=1)
        _git(source, "remote", "add", "origin", str(origin))
        _git(source, "push", "-u", "origin", "main")

        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", str(origin), str(clone)],
                       check=True, capture_output=True, text=True)
        _git(clone, "config", "user.email", "test@example.com")
        _git(clone, "config", "user.name", "Test User")
        (clone / "local.txt").write_text("local\n")
        _git(clone, "add", ".")
        _git(clone, "commit", "-m", "local only")

        snap = pulse.git_snapshot(clone)
        assert snap["upstream"] == "origin/main"
        assert snap["ahead"] == 1
        assert snap["behind"] == 0

    def test_detached_head(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo", commits=2)
        head = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=str(repo),
                              capture_output=True, text=True, check=True).stdout.strip()
        _git(repo, "checkout", head)
        snap = pulse.git_snapshot(repo)
        assert snap["detached"] is True
        assert snap["branch"] is None

    def test_empty_repo_has_no_commits(self, tmp_path: Path) -> None:
        repo = tmp_path / "empty"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        snap = pulse.git_snapshot(repo)
        assert snap["available"] is True
        assert snap["recent_commits"] == []
        assert snap["head"] is None

    def test_non_repo_degrades_with_reason(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        snap = pulse.git_snapshot(plain)
        assert snap["available"] is False
        assert snap["reason"]

    def test_missing_path_degrades_with_reason(self, tmp_path: Path) -> None:
        snap = pulse.git_snapshot(tmp_path / "nope")
        assert snap["available"] is False
        assert "does not exist" in snap["reason"]

    def test_missing_git_binary_degrades(self, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _make_repo(tmp_path / "repo")
        monkeypatch.setattr(pulse.shutil, "which", lambda _: None)
        snap = pulse.git_snapshot(repo)
        assert snap["available"] is False
        assert snap["reason"] == "git not installed"


# ---------- dispatches ----------

class TestDispatchSnapshot:
    def test_empty_project(self, fake_home: Path) -> None:
        snap = pulse.dispatch_snapshot("ghost")
        assert snap["in_flight"] == []
        assert snap["recent"] == []
        assert snap["counts"]["total"] == 0
        assert snap["last_activity_at"] is None

    def test_counts_and_recent_from_jsonl(self, fake_home: Path) -> None:
        events.log_event("proj", "d1", "start", prompt="first prompt", agent="claude")
        events.log_event("proj", "d1", "complete", ok=True, agent_used="claude",
                         duration_sec=1.5, output_preview="done")
        events.log_event("proj", "d2", "start", prompt="second prompt", agent="codex")
        events.log_event("proj", "d2", "complete", ok=False, agent_used="codex")
        events.log_event("proj", "d3", "start", prompt="third", agent="codex")
        events.log_event("proj", "d3", "cancelled")

        snap = pulse.dispatch_snapshot("proj", history=10)
        assert snap["counts"] == {
            "succeeded": 1, "failed": 1, "cancelled": 1, "total": 3,
        }
        assert len(snap["recent"]) == 3
        # Newest first, and the start event's prompt is joined onto the
        # outcome. All three land in the same millisecond here, so this
        # also locks the append-order tiebreaker.
        assert [r["dispatch_id"] for r in snap["recent"]] == ["d3", "d2", "d1"]
        by_id = {r["dispatch_id"]: r for r in snap["recent"]}
        assert by_id["d1"]["prompt"] == "first prompt"
        assert by_id["d1"]["ok"] is True
        assert by_id["d2"]["ok"] is False
        assert snap["last_activity_at"] is not None

    def test_error_event_counts_as_failure(self, fake_home: Path) -> None:
        events.log_event("proj", "d1", "start", prompt="p", agent="claude")
        events.log_event("proj", "d1", "error", error="boom")
        snap = pulse.dispatch_snapshot("proj")
        assert snap["counts"]["failed"] == 1
        assert snap["recent"][0]["error"] == "boom"

    def test_history_limit_caps_recent_but_not_counts(self, fake_home: Path) -> None:
        for i in range(6):
            events.log_event("proj", f"d{i}", "start", prompt=f"p{i}", agent="claude")
            events.log_event("proj", f"d{i}", "complete", ok=True)
        snap = pulse.dispatch_snapshot("proj", history=2)
        assert len(snap["recent"]) == 2
        assert snap["counts"]["total"] == 6

    def test_in_flight_from_shared_db(self, fake_home: Path) -> None:
        dispatches_db.upsert_started({
            "id": "live", "project": "proj", "agent": "claude",
            "status": "running", "started": time.time(), "prompt": "running now",
        })
        snap = pulse.dispatch_snapshot("proj")
        assert len(snap["in_flight"]) == 1
        assert snap["stale"] == []
        assert snap["in_flight"][0]["dispatch_id"] == "live"
        assert snap["in_flight"][0]["stale"] is False

    def test_long_running_row_is_reported_stale_not_live(self, fake_home: Path) -> None:
        """A crashed server leaves `running` rows forever — never call them live."""
        dispatches_db.upsert_started({
            "id": "zombie", "project": "proj", "agent": "opencode",
            "status": "running",
            "started": time.time() - (pulse._STALE_AFTER_SEC + 60),
            "prompt": "abandoned",
        })
        snap = pulse.dispatch_snapshot("proj")
        assert snap["in_flight"] == []
        assert len(snap["stale"]) == 1
        assert snap["stale"][0]["stale"] is True

    def test_other_projects_are_excluded(self, fake_home: Path) -> None:
        dispatches_db.upsert_started({
            "id": "elsewhere", "project": "other", "agent": "claude",
            "status": "running", "started": time.time(), "prompt": "x",
        })
        assert pulse.dispatch_snapshot("proj")["in_flight"] == []


# ---------- sessions ----------

class _ReaderAdapter(Adapter):
    def list_sessions(self, cwd, limit: int = 20):
        return [SessionInfo(id="s1", title="Recent thread",
                            modified="2026-07-20T00:00:00+00:00")]


class _ExplodingAdapter(Adapter):
    def list_sessions(self, cwd, limit: int = 20):
        raise RuntimeError("session store corrupt")


class TestSessionSnapshot:
    def test_agent_without_reader_says_so(self, fake_home: Path) -> None:
        """hermes dispatches fine but cannot enumerate sessions — say which."""
        project = registry.Project(name="p", path="/tmp", agent="hermes")
        snap = pulse.session_snapshot(project)
        assert snap["available"] is False
        assert "no session reader" in snap["reason"]

    def test_unknown_agent_falls_back_without_raising(self, fake_home: Path) -> None:
        project = registry.Project(name="p", path="/tmp", agent="not-an-agent")
        snap = pulse.session_snapshot(project)
        assert snap["available"] is False
        assert snap["reason"]

    def test_reader_results_are_surfaced(self, fake_home: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
        from central_mcp.adapters import base
        monkeypatch.setitem(base._ADAPTERS, "stub", _ReaderAdapter(name="stub"))
        project = registry.Project(name="p", path="/tmp", agent="stub")
        snap = pulse.session_snapshot(project)
        assert snap["available"] is True
        assert snap["count"] == 1
        assert snap["latest"]["id"] == "s1"

    def test_reader_failure_degrades_without_raising(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.adapters import base
        monkeypatch.setitem(base._ADAPTERS, "boom", _ExplodingAdapter(name="boom"))
        project = registry.Project(name="p", path="/tmp", agent="boom")
        snap = pulse.session_snapshot(project)
        assert snap["available"] is False
        assert "session store corrupt" in snap["reason"]


# ---------- pull requests ----------

class TestPrSnapshot:
    def test_missing_gh_degrades(self, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pulse.shutil, "which", lambda _: None)
        snap = pulse.pr_snapshot(tmp_path)
        assert snap["available"] is False
        assert snap["reason"] == "gh not installed"

    def test_gh_failure_degrades_with_stderr_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(pulse.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(pulse, "_run", lambda *a, **k: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="no git remotes found\n"))
        snap = pulse.pr_snapshot(tmp_path)
        assert snap["available"] is False
        assert snap["reason"] == "no git remotes found"

    def test_open_prs_are_parsed(self, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
        payload = json.dumps([{
            "number": 12, "title": "Add pulse", "headRefName": "feat/pulse",
            "isDraft": True, "updatedAt": "2026-07-25T00:00:00Z",
            "url": "https://example.test/pr/12",
        }])
        monkeypatch.setattr(pulse.shutil, "which", lambda _: "/usr/bin/gh")
        monkeypatch.setattr(pulse, "_run", lambda *a, **k: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=payload, stderr=""))
        snap = pulse.pr_snapshot(tmp_path)
        assert snap["available"] is True
        assert snap["count"] == 1
        assert snap["open"][0]["number"] == 12
        assert snap["open"][0]["draft"] is True
        assert snap["open"][0]["age_sec"] is not None


# ---------- the pulse ----------

@needs_git
class TestPulse:
    def test_unknown_project(self, fake_home: Path) -> None:
        r = pulse.pulse("ghost")
        assert r["ok"] is False
        assert "unknown project" in r["error"]

    def test_assembles_every_section(self, fake_home: Path, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        events.log_event("proj", "d1", "start", prompt="do the thing", agent="hermes")
        events.log_event("proj", "d1", "complete", ok=True)

        r = pulse.pulse("proj", include_pr=False)
        assert r["ok"] is True
        assert r["project"] == "proj"
        assert r["agent"] == "hermes"
        assert r["git"]["available"] is True
        assert r["dispatches"]["counts"]["succeeded"] == 1
        assert r["pull_requests"]["reason"] == "not requested"
        assert r["last_activity_at"] is not None
        assert r["last_activity_age_sec"] >= 0

    def test_last_activity_takes_the_most_recent_source(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        """A dispatch just now beats the commit that preceded it."""
        repo = _make_repo(tmp_path / "repo")
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        commit_ts = pulse.pulse("proj", include_pr=False)["last_activity_at"]

        events.log_event("proj", "d1", "start", prompt="p", agent="hermes")
        events.log_event("proj", "d1", "complete", ok=True)
        after = pulse.pulse("proj", include_pr=False)["last_activity_at"]
        assert pulse._parse_iso(after) >= pulse._parse_iso(commit_ts)

    def test_last_activity_is_normalized_to_utc(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        """Cross-project string comparison must order by instant, not by
        whatever offset the source happened to use."""
        repo = _make_repo(tmp_path / "repo")
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        ts = pulse.pulse("proj", include_pr=False)["last_activity_at"]
        assert ts.endswith("+00:00")

    def test_git_failure_does_not_sink_the_pulse(self, fake_home: Path,
                                                 tmp_path: Path) -> None:
        registry.add_project(name="proj", path_=str(tmp_path / "gone"), agent="hermes")
        r = pulse.pulse("proj", include_pr=False)
        assert r["ok"] is True
        assert r["git"]["available"] is False
        assert r["git"]["reason"]

    def test_pulse_many_preserves_order(self, fake_home: Path, tmp_path: Path) -> None:
        for name in ("alpha", "beta", "gamma"):
            registry.add_project(
                name=name, path_=str(_make_repo(tmp_path / name)), agent="hermes"
            )
        results = pulse.pulse_many(registry.load_registry(), include_pr=False)
        assert [r["project"] for r in results] == ["alpha", "beta", "gamma"]

    def test_pulse_many_isolates_a_failing_project(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry.add_project(name="ok1", path_=str(_make_repo(tmp_path / "ok1")),
                             agent="hermes")
        registry.add_project(name="bad", path_=str(tmp_path / "bad"), agent="hermes")

        real = pulse.pulse_for

        def _explode(project, **kwargs):
            if project.name == "bad":
                raise RuntimeError("kaboom")
            return real(project, **kwargs)

        monkeypatch.setattr(pulse, "pulse_for", _explode)
        results = pulse.pulse_many(registry.load_registry(), include_pr=False)
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert "kaboom" in results[1]["error"]

    def test_pulse_many_empty(self, fake_home: Path) -> None:
        assert pulse.pulse_many([]) == []


# ---------- rendering ----------

@needs_git
class TestRender:
    def test_render_is_single_line_per_entry(self, fake_home: Path,
                                             tmp_path: Path) -> None:
        """Regression: multi-paragraph prompts used to break list rendering."""
        repo = _make_repo(tmp_path / "repo")
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        events.log_event("proj", "d1", "start",
                         prompt="line one\n\nline two\nline three", agent="hermes")
        events.log_event("proj", "d1", "complete", ok=True)

        text = pulse.render(pulse.pulse("proj", include_pr=False))
        entry_lines = [ln for ln in text.splitlines() if ln.lstrip().startswith("- ")]
        assert any("line one line two line three" in ln for ln in entry_lines)

    def test_render_reports_stale_separately(self, fake_home: Path,
                                             tmp_path: Path) -> None:
        repo = _make_repo(tmp_path / "repo")
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        dispatches_db.upsert_started({
            "id": "zombie", "project": "proj", "agent": "gemini",
            "status": "running",
            "started": time.time() - (pulse._STALE_AFTER_SEC + 60),
            "prompt": "abandoned",
        })
        text = pulse.render(pulse.pulse("proj", include_pr=False))
        assert "0 in flight" in text
        assert "1 stale" in text
        assert "never finalized" in text

    def test_render_error_pulse(self) -> None:
        text = pulse.render({"ok": False, "project": "ghost", "error": "unknown"})
        assert "ghost" in text
        assert "unknown" in text

    def test_render_many_includes_every_project(self, fake_home: Path,
                                                tmp_path: Path) -> None:
        for name in ("alpha", "beta"):
            registry.add_project(
                name=name, path_=str(_make_repo(tmp_path / name)), agent="hermes"
            )
        text = pulse.render_many(
            pulse.pulse_many(registry.load_registry(), include_pr=False),
            title="Sweep",
        )
        assert "## Sweep" in text
        assert "### alpha" in text
        assert "### beta" in text

    def test_render_many_empty(self) -> None:
        assert "no projects" in pulse.render_many([])


# ---------- events.read_jsonl (shared reader) ----------

class TestReadJsonl:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert events.read_jsonl(tmp_path / "nope.jsonl") == []

    def test_skips_unparseable_and_non_object_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text(
            '{"a": 1}\n'
            "\n"
            "{not json\n"
            "[1, 2]\n"          # valid JSON, wrong shape
            '{"b": 2}\n'
        )
        assert events.read_jsonl(path) == [{"a": 1}, {"b": 2}]

    def test_partial_trailing_line_is_tolerated(self, tmp_path: Path) -> None:
        path = tmp_path / "log.jsonl"
        path.write_text('{"a": 1}\n{"b": ')
        assert events.read_jsonl(path) == [{"a": 1}]


# ---------- MCP tool surface ----------

@needs_git
class TestProjectPulseTool:
    def test_unknown_project(self, fake_home: Path) -> None:
        from central_mcp import server
        r = server.project_pulse("ghost")
        assert r["ok"] is False

    def test_returns_pulse_for_registered_project(self, fake_home: Path,
                                                  tmp_path: Path) -> None:
        from central_mcp import server
        repo = _make_repo(tmp_path / "repo")
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        r = server.project_pulse("proj", include_pr=False)
        assert r["ok"] is True
        assert r["git"]["branch"] == "main"

    def test_negative_limits_are_clamped(self, fake_home: Path,
                                         tmp_path: Path) -> None:
        from central_mcp import server
        repo = _make_repo(tmp_path / "repo", commits=2)
        registry.add_project(name="proj", path_=str(repo), agent="hermes")
        r = server.project_pulse("proj", commits=-5, history=-5, include_pr=False)
        assert r["git"]["recent_commits"] == []
        assert r["dispatches"]["recent"] == []
