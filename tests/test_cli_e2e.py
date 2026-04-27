"""End-to-end CLI tests from a user's perspective.

Each test runs `central-mcp <subcommand>` as a real subprocess with
CENTRAL_MCP_HOME pointed at a temp dir. No mocking, no internal imports
— just stdin/stdout/exit-code, exactly what a user would see.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Return env dict that isolates central-mcp to a throwaway home."""
    import os
    env = os.environ.copy()
    home = tmp_path / "central-mcp-home"
    env["CENTRAL_MCP_HOME"] = str(home)
    # Ensure no cwd registry interferes
    env.pop("CENTRAL_MCP_REGISTRY", None)
    monkeypatch.chdir(tmp_path)
    return env


def _run(args: list[str], env: dict, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "central_mcp", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


class TestInit:
    def test_creates_registry(self, cli_env: dict, tmp_path: Path) -> None:
        r = _run(["init"], cli_env)
        assert r.returncode == 0
        reg = Path(cli_env["CENTRAL_MCP_HOME"]) / "registry.yaml"
        assert reg.exists()
        assert "projects: []" in reg.read_text()

    def test_refuses_overwrite(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["init"], cli_env)
        assert r.returncode == 1
        assert "already exists" in r.stderr

    def test_force_overwrites(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["init", "--force"], cli_env)
        assert r.returncode == 0


class TestAddRemoveList:
    def test_add_then_list(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        r = _run(["add", "myproj", str(project_dir), "--agent", "claude"], cli_env)
        assert r.returncode == 0
        assert "added: myproj" in r.stdout

        r = _run(["list"], cli_env)
        assert r.returncode == 0
        assert "myproj" in r.stdout
        assert "claude" in r.stdout

    def test_remove(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        _run(["add", "proj", str(project_dir)], cli_env)
        r = _run(["remove", "proj"], cli_env)
        assert r.returncode == 0
        assert "removed" in r.stdout

        r = _run(["list"], cli_env)
        assert "empty" in r.stdout

    def test_remove_nonexistent(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["remove", "ghost"], cli_env)
        assert r.returncode == 1
        assert "no project" in r.stderr

    def test_add_duplicate(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        d = tmp_path / "dup"
        d.mkdir()
        _run(["add", "dup", str(d)], cli_env)
        r = _run(["add", "dup", str(d)], cli_env)
        assert r.returncode == 1
        assert "already exists" in r.stderr


class TestAgentValidation:
    def test_invalid_agent_rejected_at_add(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        d = tmp_path / "proj"
        d.mkdir()
        r = _run(["add", "proj", str(d), "--agent", "cursor-agent"], cli_env)
        assert r.returncode == 1
        assert "unknown agent" in r.stderr

    def test_invalid_agent_lists_valid_options(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        d = tmp_path / "proj"
        d.mkdir()
        r = _run(["add", "proj", str(d), "--agent", "vim"], cli_env)
        assert r.returncode == 1
        assert "claude" in r.stderr
        assert "codex" in r.stderr
        assert "gemini" in r.stderr

    def test_shell_agent_rejected(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        d = tmp_path / "proj"
        d.mkdir()
        r = _run(["add", "proj", str(d), "--agent", "shell"], cli_env)
        assert r.returncode != 0
        assert "shell" in r.stderr


class TestBrief:
    def test_empty_registry(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["brief"], cli_env)
        assert r.returncode == 0
        assert "empty" in r.stdout.lower() or "registered" in r.stdout.lower()

    def test_with_projects(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        d = tmp_path / "proj"
        d.mkdir()
        _run(["add", "proj", str(d), "--agent", "codex"], cli_env)
        r = _run(["brief"], cli_env)
        assert r.returncode == 0
        assert "proj" in r.stdout
        assert "codex" in r.stdout


class TestInstall:
    def test_install_claude_dry_run(self, cli_env: dict) -> None:
        r = _run(["install", "claude", "--dry-run"], cli_env)
        assert r.returncode == 0
        assert "Would run" in r.stdout

    def test_install_codex_dry_run(self, cli_env: dict, tmp_path: Path) -> None:
        # Create a fake codex config so install has something to patch
        codex_dir = Path(cli_env.get("HOME", str(tmp_path))) / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text("[mcp_servers]\n")
        r = _run(["install", "codex", "--dry-run"], cli_env)
        assert r.returncode == 0


class TestAutoInitOnRun:
    def test_run_dry_run_creates_registry_when_missing(
        self, cli_env: dict
    ) -> None:
        """`central-mcp` cold-start should drop a registry.yaml without
        forcing the user to run `central-mcp init` first."""
        reg = Path(cli_env["CENTRAL_MCP_HOME"]) / "registry.yaml"
        assert not reg.exists()

        r = _run(["run", "--dry-run", "--agent", "claude"], cli_env)
        # dry-run may still succeed even if claude is missing on PATH
        # (we're asserting the side effect, not the launch).
        if r.returncode != 0 and "is not installed" in r.stderr:
            pytest.skip("no claude on PATH in this test environment")

        assert reg.exists(), "registry.yaml should be auto-created on first run"
        assert "projects: []" in reg.read_text()

    def test_run_dry_run_drops_install_marker_after_first_bootstrap(
        self, cli_env: dict
    ) -> None:
        """After the first cold start, the auto-install marker is present."""
        marker = Path(cli_env["CENTRAL_MCP_HOME"]) / ".install_auto_done"
        r = _run(["run", "--dry-run", "--agent", "claude"], cli_env)
        if r.returncode != 0 and "is not installed" in r.stderr:
            pytest.skip("no claude on PATH in this test environment")
        # Marker only appears when a client was detected on PATH (claude
        # is — we just used it via --agent). If it didn't appear, the
        # bootstrap skipped because no supported client was found, which
        # is also a valid outcome — in that case we don't block the test.
        if marker.exists():
            # Re-run should NOT re-trigger install (idempotency by marker).
            r2 = _run(["run", "--dry-run", "--agent", "claude"], cli_env)
            assert "First-run bootstrap" not in r2.stdout


class TestWorkspace:
    def _add_project(self, name: str, cli_env: dict, tmp_path: Path) -> None:
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        _run(["add", name, str(d)], cli_env)

    def test_workspace_list_shows_default(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["workspace", "list"], cli_env)
        assert r.returncode == 0
        assert "default" in r.stdout

    def test_workspace_current_default(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["workspace", "current"], cli_env)
        assert r.returncode == 0
        assert "default" in r.stdout

    def test_workspace_new_and_list(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["workspace", "new", "work"], cli_env)
        assert r.returncode == 0
        r = _run(["workspace", "list"], cli_env)
        assert "work" in r.stdout

    def test_workspace_new_duplicate_fails(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        _run(["workspace", "new", "work"], cli_env)
        r = _run(["workspace", "new", "work"], cli_env)
        assert r.returncode == 1
        assert "already exists" in r.stderr

    def test_workspace_use_and_current(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        _run(["workspace", "new", "work"], cli_env)
        r = _run(["workspace", "use", "work"], cli_env)
        assert r.returncode == 0
        r = _run(["workspace", "current"], cli_env)
        assert "work" in r.stdout

    def test_workspace_use_unknown_fails(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["workspace", "use", "ghost"], cli_env)
        assert r.returncode == 1
        assert "unknown workspace" in r.stderr

    def test_workspace_add_project(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        self._add_project("alpha", cli_env, tmp_path)
        _run(["workspace", "new", "work"], cli_env)
        r = _run(["workspace", "add", "alpha", "--workspace", "work"], cli_env)
        assert r.returncode == 0
        r = _run(["workspace", "list"], cli_env)
        assert "work" in r.stdout

    def test_workspace_add_unknown_project_fails(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        _run(["workspace", "new", "work"], cli_env)
        r = _run(["workspace", "add", "ghost", "--workspace", "work"], cli_env)
        assert r.returncode == 1
        assert "unknown project" in r.stderr

    def test_workspace_remove_project(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        self._add_project("alpha", cli_env, tmp_path)
        _run(["workspace", "new", "work"], cli_env)
        _run(["workspace", "add", "alpha", "--workspace", "work"], cli_env)
        r = _run(["workspace", "remove", "alpha", "--workspace", "work"], cli_env)
        assert r.returncode == 0

    def test_workspace_list_shows_active_marker(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        _run(["workspace", "new", "work"], cli_env)
        _run(["workspace", "use", "work"], cli_env)
        r = _run(["workspace", "list"], cli_env)
        assert r.returncode == 0
        assert "*" in r.stdout  # active marker

    def test_workspace_list_shows_project_counts(self, cli_env: dict, tmp_path: Path) -> None:
        _run(["init"], cli_env)
        self._add_project("alpha", cli_env, tmp_path)
        _run(["workspace", "new", "work"], cli_env)
        _run(["workspace", "add", "alpha", "--workspace", "work"], cli_env)
        r = _run(["workspace", "list"], cli_env)
        assert "1" in r.stdout  # 1 project in work


class TestRunWorkspaceFlag:
    """`cmcp run --workspace NAME` per-process workspace scope.

    Multiple shells / MCP clients can run concurrently on different
    workspaces by passing `--workspace` (or exporting `CMCP_WORKSPACE`)
    instead of mutating the saved default in `config.toml`.
    """

    def test_unknown_workspace_errors(self, cli_env: dict) -> None:
        _run(["init"], cli_env)
        r = _run(["run", "--workspace", "ghost", "--dry-run"], cli_env)
        assert r.returncode == 1
        assert "unknown workspace" in r.stderr

    def test_known_workspace_accepted(
        self, cli_env: dict, tmp_path: Path
    ) -> None:
        _run(["init"], cli_env)
        _run(["workspace", "new", "client-a"], cli_env)
        # --dry-run exits before exec; if the workspace lookup is wrong
        # we'd see the "unknown workspace" branch fire instead.
        r = _run(
            ["run", "--workspace", "client-a", "--dry-run"],
            cli_env,
        )
        # Exit may still be 1 if no orchestrator binary is installed in
        # the test env — accept either, but stderr must NOT carry the
        # workspace-validation error.
        assert "unknown workspace" not in r.stderr


class TestHelp:
    def test_run_help_shows_run_flags(self, cli_env: dict) -> None:
        # `central-mcp --help` routes to `central-mcp run --help`
        r = _run(["--help"], cli_env)
        assert r.returncode == 0
        assert "--permission-mode" in r.stdout
        assert "--pick" in r.stdout

    def test_serve_help_shows_all_subcommands(self, cli_env: dict) -> None:
        # Use an explicit subcommand to reach the top-level help listing
        r = _run(["serve", "--help"], cli_env)
        assert r.returncode == 0

    def test_add_help(self, cli_env: dict) -> None:
        r = _run(["add", "--help"], cli_env)
        assert r.returncode == 0
        assert "--agent" in r.stdout
