"""Tests for the ledger's write surfaces: the `project_note` MCP tool
(the primary path — an agent recording its own work) and `cmcp note`
(a human at a terminal).

The recurring theme is *attribution*. The ledger is only worth reading if
a reader can tell a first-hand record from a relayed one, so these tests
care as much about who an entry is credited to as about whether it landed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import central_mcp.server as srv
from central_mcp import ledger, registry


@pytest.fixture
def project(fake_home: Path, tmp_path: Path) -> registry.Project:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    return registry.add_project("proj", str(root))


class TestProjectNoteTool:
    def test_writes_an_entry_by_name(self, project: registry.Project) -> None:
        result = srv.project_note(
            note="tried the worktree route, abandoned it", name="proj"
        )
        assert result["ok"] is True
        assert result["resolved_by"] == "name"
        entries = ledger.read("proj")
        assert len(entries) == 1
        assert entries[0].body == "tried the worktree route, abandoned it"

    def test_defaults_to_agent_source(self, project: registry.Project) -> None:
        """An agent recording its own work is the common case, so it is
        the default — but it must be explicit in the file."""
        srv.project_note(note="did the thing", name="proj")
        assert ledger.read("proj")[0].source == "agent"

    def test_user_source_is_recorded_distinctly(
        self, project: registry.Project
    ) -> None:
        srv.project_note(note="human said so", name="proj", source="user")
        assert ledger.read("proj")[0].source == "user"

    def test_rejects_a_fabricated_source(self, project: registry.Project) -> None:
        result = srv.project_note(note="x", name="proj", source="inferred")
        assert result["ok"] is False
        assert "source must be one of" in result["error"]
        assert ledger.read("proj") == []

    def test_next_step_is_stored(self, project: registry.Project) -> None:
        srv.project_note(note="wip", name="proj", next_step="finish the parser")
        assert ledger.read("proj")[0].next_step == "finish the parser"

    def test_resolves_from_a_path_inside_the_project(
        self, project: registry.Project
    ) -> None:
        """A session knows where it is, not necessarily what it's called."""
        result = srv.project_note(note="from a subdir", cwd=str(Path(project.path) / "src"))
        assert result["ok"] is True
        assert result["project"] == "proj"
        assert result["resolved_by"] == "cwd"

    def test_unregistered_path_is_an_actionable_error(
        self, project: registry.Project, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        result = srv.project_note(note="x", cwd=str(elsewhere))
        assert result["ok"] is False
        assert "no registered project" in result["error"]
        assert "hint" in result

    def test_unknown_name_does_not_write(self, project: registry.Project) -> None:
        result = srv.project_note(note="x", name="nope")
        assert result["ok"] is False
        assert not ledger.exists("nope")

    def test_falls_back_to_the_server_cwd(
        self, project: registry.Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The server inherits the cwd of the agent that launched it, so a
        session opened inside a project can record without naming it."""
        monkeypatch.chdir(project.path)
        result = srv.project_note(note="ambient")
        assert result["ok"] is True
        assert result["resolved_by"] == "server_cwd"

    def test_empty_note_is_refused(self, project: registry.Project) -> None:
        result = srv.project_note(note="   ", name="proj")
        assert result["ok"] is False
        assert "empty" in result["error"]

    def test_entries_accumulate(self, project: registry.Project) -> None:
        srv.project_note(note="one", name="proj")
        srv.project_note(note="two", name="proj")
        assert [e.body for e in ledger.read("proj")] == ["two", "one"]


# ---------- CLI ----------

def _run(args: list[str], env: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "central_mcp", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=30,
    )


@pytest.fixture
def cli(tmp_path: Path) -> tuple[dict, Path, Path]:
    env = os.environ.copy()
    home = tmp_path / "central-mcp-home"
    env["CENTRAL_MCP_HOME"] = str(home)
    env.pop("CENTRAL_MCP_REGISTRY", None)
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    subprocess.run(
        [sys.executable, "-m", "central_mcp", "add", "proj", str(repo)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=30,
    )
    return env, repo, home


class TestNoteCLI:
    def test_notes_the_project_owning_the_cwd(self, cli) -> None:
        env, repo, home = cli
        r = _run(["note", "explored X, dead end"], env, repo / "src")
        assert r.returncode == 0, r.stderr
        assert "noted" in r.stdout
        assert "explored X, dead end" in (home / "projects" / "proj" / "STATUS.md").read_text()

    def test_cli_entries_are_attributed_to_the_user(self, cli) -> None:
        """A person typing at a terminal is a `user` by definition, and the
        CLI offers no way to claim otherwise."""
        env, repo, home = cli
        _run(["note", "my own words"], env, repo)
        text = (home / "projects" / "proj" / "STATUS.md").read_text()
        assert "· user" in text
        assert "· agent" not in text

    def test_project_flag_targets_another_project(self, cli, tmp_path: Path) -> None:
        env, repo, home = cli
        r = _run(["note", "-p", "proj", "from elsewhere"], env, tmp_path)
        assert r.returncode == 0, r.stderr

    def test_outside_any_project_fails_with_guidance(self, cli, tmp_path: Path) -> None:
        env, repo, home = cli
        outside = tmp_path / "outside"
        outside.mkdir()
        r = _run(["note", "orphan"], env, outside)
        assert r.returncode == 1
        assert "--project" in r.stderr

    def test_next_flag(self, cli) -> None:
        env, repo, home = cli
        r = _run(["note", "-n", "wire up the sidebar"], env, repo)
        assert r.returncode == 0, r.stderr
        assert "Next: wire up the sidebar" in (
            home / "projects" / "proj" / "STATUS.md"
        ).read_text()

    def test_nothing_to_record_is_refused(self, cli) -> None:
        env, repo, home = cli
        r = _run(["note"], env, repo)
        assert r.returncode == 1
        assert "nothing to record" in r.stderr

    def test_show_prints_entries(self, cli) -> None:
        env, repo, home = cli
        _run(["note", "first thing"], env, repo)
        _run(["note", "second thing", "-n", "then this"], env, repo)
        r = _run(["note", "--show"], env, repo)
        assert r.returncode == 0, r.stderr
        assert "first thing" in r.stdout
        assert "second thing" in r.stdout
        assert "Next: then this" in r.stdout

    def test_show_on_an_empty_ledger(self, cli) -> None:
        env, repo, home = cli
        r = _run(["note", "--show"], env, repo)
        assert r.returncode == 0
        assert "no ledger entries" in r.stdout

    def test_unknown_project_fails(self, cli, tmp_path: Path) -> None:
        env, repo, home = cli
        r = _run(["note", "-p", "ghost", "x"], env, tmp_path)
        assert r.returncode == 1
        assert "unknown project" in r.stderr


# ---------- dispatch capture (the secondary write path) ----------

class TestStatusBlockCapture:
    """A dispatched agent is asked to leave a STATUS block; central-mcp
    transcribes it. It never summarizes the output itself — the agent is
    the only party that knows what it meant to do."""

    def test_parses_a_well_formed_block(self) -> None:
        parsed = srv._parse_status_block(
            "chatter\n"
            "<!-- CENTRAL-MCP STATUS\n"
            "Done: rewired the parser\n"
            "Left: the CLI flag\n"
            "Next: wire the CLI flag\n"
            "-->\n"
        )
        assert parsed is not None
        body, next_step = parsed
        assert "rewired the parser" in body
        assert "the CLI flag" in body
        assert next_step == "wire the CLI flag"

    def test_absent_block_returns_none(self) -> None:
        assert srv._parse_status_block("just some output") is None

    def test_empty_block_returns_none(self) -> None:
        assert srv._parse_status_block("<!-- CENTRAL-MCP STATUS\n\n-->") is None

    def test_last_block_wins(self) -> None:
        """An agent that echoes the template before filling it in must not
        have its example recorded as fact."""
        parsed = srv._parse_status_block(
            "<!-- CENTRAL-MCP STATUS\nDone: what you actually changed\n-->\n"
            "...working...\n"
            "<!-- CENTRAL-MCP STATUS\nDone: the real thing\n-->"
        )
        assert parsed is not None and parsed[0] == "Done: the real thing"

    def test_records_a_successful_dispatch(self, project: registry.Project) -> None:
        srv._record_dispatch_status(
            "proj",
            "complete",
            "<!-- CENTRAL-MCP STATUS\nDone: shipped it\nNext: tell the user\n-->",
        )
        entries = ledger.read("proj")
        assert len(entries) == 1
        assert entries[0].source == "agent"
        assert entries[0].next_step == "tell the user"

    def test_successful_dispatch_without_a_block_records_nothing(
        self, project: registry.Project
    ) -> None:
        srv._record_dispatch_status("proj", "complete", "I did some stuff.")
        assert ledger.read("proj") == []

    @pytest.mark.parametrize("status", ["error", "timeout", "cancelled"])
    def test_failed_dispatch_records_nothing(
        self, project: registry.Project, status: str
    ) -> None:
        """A stub for a failed dispatch would advance the watermark and so
        *silence* the drift signal for work that was never recorded."""
        srv._record_dispatch_status(
            "proj", status, "<!-- CENTRAL-MCP STATUS\nDone: partial\n-->"
        )
        assert ledger.read("proj") == []

    def test_recording_never_raises(self, project: registry.Project) -> None:
        """The ledger is additive; it must never be able to fail a dispatch."""
        srv._record_dispatch_status(
            "no-such-project/../..", "complete",
            "<!-- CENTRAL-MCP STATUS\nDone: x\n-->",
        )

    def test_preface_asks_for_the_block_last(self) -> None:
        """Recency is the cheapest defense against a dropped instruction."""
        assert "CENTRAL-MCP STATUS" in srv._STATUS_PREFACE
        assert srv._STATUS_PREFACE.rstrip().endswith("-->")
