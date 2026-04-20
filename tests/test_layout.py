"""tmux observation layer tests.

These tests require tmux to be installed. They create and destroy real
tmux sessions in isolated names so they don't collide with the user's
own sessions. Skipped automatically if tmux is not on PATH.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from central_mcp import layout, registry, tmux

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None,
    reason="tmux not installed",
)


@pytest.fixture(autouse=True)
def _cleanup_session():
    """Kill the test session after each test, even on failure."""
    yield
    if tmux.has_session(layout.SESSION):
        tmux.kill_session(layout.SESSION)


class TestEnsureSession:
    def test_creates_session_with_projects(self, fake_home: Path, tmp_path: Path) -> None:
        d1 = tmp_path / "proj-a"
        d1.mkdir()
        d2 = tmp_path / "proj-b"
        d2.mkdir()
        registry.add_project("proj-a", str(d1), agent="claude")
        registry.add_project("proj-b", str(d2), agent="codex")

        created, messages = layout.ensure_session()
        assert created is True
        assert tmux.has_session(layout.SESSION)
        assert any("proj-a" in m for m in messages)
        assert any("proj-b" in m for m in messages)

    def test_idempotent_rerun(self, fake_home: Path, tmp_path: Path) -> None:
        d = tmp_path / "proj"
        d.mkdir()
        registry.add_project("proj", str(d))

        created1, _ = layout.ensure_session()
        assert created1 is True
        created2, msgs2 = layout.ensure_session()
        assert created2 is False
        assert any("already exists" in m for m in msgs2)

    def test_empty_registry(self, fake_home: Path) -> None:
        created, messages = layout.ensure_session()
        assert created is True
        assert any("no projects" in m.lower() for m in messages)
        assert tmux.has_session(layout.SESSION)


class TestKillAll:
    def test_kills_existing_session(self, fake_home: Path) -> None:
        tmux.new_session(layout.SESSION, "test", ".")
        assert tmux.has_session(layout.SESSION)
        killed, msg = layout.kill_all()
        assert killed is True
        assert not tmux.has_session(layout.SESSION)

    def test_no_session_to_kill(self, fake_home: Path) -> None:
        killed, msg = layout.kill_all()
        assert killed is False
        assert "no session" in msg.lower()


class TestPaneDetails:
    """Verify pane count, cwd, and render integrity."""

    def test_pane_count_matches_projects(self, fake_home: Path, tmp_path: Path) -> None:
        for i in range(3):
            d = tmp_path / f"proj-{i}"
            d.mkdir()
            registry.add_project(f"proj-{i}", str(d), agent="shell")

        layout.ensure_session()
        first = layout.window_name(0)
        r = tmux._run([
            "list-panes", "-t", f"{layout.SESSION}:{first}",
            "-F", "#{pane_index}",
        ])
        assert r.ok
        pane_count = len(r.stdout.strip().splitlines())
        assert pane_count == 3

    def test_pane_cwd_matches_project_path(self, fake_home: Path, tmp_path: Path) -> None:
        d = tmp_path / "my-proj"
        d.mkdir()
        registry.add_project("my-proj", str(d), agent="shell")

        layout.ensure_session()
        first = layout.window_name(0)
        r = tmux._run([
            "list-panes", "-t", f"{layout.SESSION}:{first}",
            "-F", "#{pane_current_path}",
        ])
        assert r.ok
        # Resolve both to handle /private/tmp vs /tmp on macOS
        actual = Path(r.stdout.strip().splitlines()[0]).resolve()
        expected = d.resolve()
        assert actual == expected

    def test_capture_pane_no_garbled_output(self, fake_home: Path, tmp_path: Path) -> None:
        """Capture the pane viewport and check for common corruption markers."""
        d = tmp_path / "proj"
        d.mkdir()
        registry.add_project("proj", str(d), agent="shell")

        layout.ensure_session()
        import time
        time.sleep(0.3)  # let shell prompt render

        first = layout.window_name(0)
        r = tmux._run([
            "capture-pane", "-p", "-t", f"{layout.SESSION}:{first}.0",
        ])
        assert r.ok
        text = r.stdout
        # No raw escape sequences should leak into the captured viewport
        assert "\x1b" not in text, f"raw escape sequence in pane output: {text[:200]}"
        # No NUL bytes
        assert "\x00" not in text

    def test_multiple_panes_have_tiled_layout(self, fake_home: Path, tmp_path: Path) -> None:
        for i in range(2):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        layout.ensure_session()
        r = tmux._run([
            "list-windows", "-t", layout.SESSION,
            "-F", "#{window_layout}",
        ])
        assert r.ok
        # tiled layout produces a specific pattern; at minimum confirm
        # there's a layout string (not empty)
        layout_str = r.stdout.strip().splitlines()[0]
        assert len(layout_str) > 5  # e.g. "a1b2,80x24,0,0{40x24,0,0,1,39x24,41,0,2}"


class TestUpDown:
    def test_up_then_down(self, fake_home: Path, tmp_path: Path) -> None:
        d = tmp_path / "proj"
        d.mkdir()
        registry.add_project("proj", str(d), agent="gemini")

        created, _ = layout.ensure_session()
        assert created
        assert tmux.has_session(layout.SESSION)

        killed, _ = layout.kill_all()
        assert killed
        assert not tmux.has_session(layout.SESSION)


class TestOrchestratorPane:
    """Pane 0 is the orchestrator when OrchestratorPane is passed."""

    def test_orchestrator_becomes_pane_zero(self, fake_home: Path, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        registry.add_project("proj", str(project_dir), agent="shell")

        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub-orch")

        created, messages = layout.ensure_session(orchestrator=orch)
        assert created
        # Pane 0 should be orchestrator; project panes added via the flat
        # grid helper log `{wname} -> {title}` (no numeric pane index).
        first = layout.window_name(0, has_orchestrator=True)
        assert first.endswith(layout.HUB_SUFFIX)
        assert any("pane 0 ->" in m and "Central MCP Orchestrator" in m and first in m for m in messages)
        assert any(f"{first} -> proj" in m for m in messages)

        r = tmux._run([
            "list-panes", "-t", f"{layout.SESSION}:{first}",
            "-F", "#{pane_index}:#{pane_current_path}",
        ])
        assert r.ok
        lines = r.stdout.strip().splitlines()
        assert len(lines) == 2
        # Resolve paths to handle /tmp vs /private/tmp on macOS.
        assert Path(lines[0].split(":", 1)[1]).resolve() == orch_dir.resolve()
        assert Path(lines[1].split(":", 1)[1]).resolve() == project_dir.resolve()

    def test_no_orchestrator_keeps_projects_at_index_zero(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        d = tmp_path / "only-proj"
        d.mkdir()
        registry.add_project("only-proj", str(d), agent="shell")

        created, messages = layout.ensure_session(orchestrator=None)
        assert created
        assert any("pane 0 -> only-proj" in m for m in messages)

    def test_orchestrator_only_empty_registry(self, fake_home: Path, tmp_path: Path) -> None:
        """Orchestrator still spawns even when no projects are registered."""
        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub")

        created, messages = layout.ensure_session(orchestrator=orch)
        assert created
        assert any("pane 0 ->" in m and "Central MCP Orchestrator" in m for m in messages)


def _window_names(session: str) -> list[str]:
    r = tmux._run(["list-windows", "-t", session, "-F", "#{window_name}"])
    assert r.ok
    return r.stdout.strip().splitlines()


def _pane_count(session: str, window: str) -> int:
    r = tmux._run(["list-panes", "-t", f"{session}:{window}", "-F", "#{pane_index}"])
    assert r.ok
    return len(r.stdout.strip().splitlines())


class TestWindowChunking:
    """Panes are split across windows at PANES_PER_WINDOW boundaries."""

    def test_four_items_fit_in_one_window(self, fake_home: Path, tmp_path: Path) -> None:
        for i in range(4):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        created, messages = layout.ensure_session()
        assert created
        assert not any("failed" in m for m in messages), messages
        w1 = layout.window_name(0)
        assert _window_names(layout.SESSION) == [w1]
        assert _pane_count(layout.SESSION, w1) == 4

    def test_five_items_overflow_to_second_window(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        for i in range(5):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        created, messages = layout.ensure_session()
        assert created
        assert not any("failed" in m for m in messages), messages
        w1, w2 = layout.window_name(0), layout.window_name(1)
        assert _window_names(layout.SESSION) == [w1, w2]
        assert _pane_count(layout.SESSION, w1) == 4
        assert _pane_count(layout.SESSION, w2) == 1

    def test_hub_holds_fewer_panes_when_orchestrator_present(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        # panes_per_window=4 + orch → hub holds orch + 2 projects (3 panes).
        # Orch visually takes two cells via main-vertical so the window
        # still feels like `panes_per_window` cells worth.
        for i in range(2):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub")

        created, messages = layout.ensure_session(orchestrator=orch)
        assert created
        hub = layout.window_name(0, has_orchestrator=True)
        assert hub.endswith(layout.HUB_SUFFIX)
        assert _window_names(layout.SESSION) == [hub]
        assert _pane_count(layout.SESSION, hub) == 3

    def test_orchestrator_plus_four_projects_overflows_to_second_window(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        # 0.6.3+: orchestrator no longer takes extra visual weight, so
        # the first window holds the full panes_per_window count.
        # panes_per_window=4 + orch + 4 projects → first window (4: orch
        # + 3 projects) + overflow (1 project).
        for i in range(4):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub")

        created, messages = layout.ensure_session(orchestrator=orch)
        assert created
        assert not any("failed" in m for m in messages), messages
        hub = layout.window_name(0, has_orchestrator=True)
        overflow = layout.window_name(1, has_orchestrator=True)
        assert _window_names(layout.SESSION) == [hub, overflow]
        assert _pane_count(layout.SESSION, hub) == 4
        assert _pane_count(layout.SESSION, overflow) == 1

    def test_orchestrator_plus_eight_projects_chunks_into_three_windows(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        # 0.6.3+: flat chunking — every window holds up to panes_per_window
        # panes, orchestrator counts as one. 1 orch + 8 projects = 9 total
        # → 4 + 4 + 1 with panes_per_window=4.
        for i in range(8):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub")

        created, messages = layout.ensure_session(orchestrator=orch)
        assert created
        names = _window_names(layout.SESSION)
        assert len(names) == 3
        assert _pane_count(layout.SESSION, names[0]) == 4
        assert _pane_count(layout.SESSION, names[1]) == 4
        assert _pane_count(layout.SESSION, names[2]) == 1

    def test_twenty_projects_span_multiple_windows(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        # 20 projects → ceil(20/4) = 5 windows: 4 + 4 + 4 + 4 + 4.
        for i in range(20):
            d = tmp_path / f"p{i:02d}"
            d.mkdir()
            registry.add_project(f"p{i:02d}", str(d), agent="shell")

        created, messages = layout.ensure_session()
        assert created
        assert not any("failed" in m for m in messages), messages

        names = _window_names(layout.SESSION)
        assert names == [layout.window_name(i) for i in range(5)]
        for name in names:
            assert _pane_count(layout.SESSION, name) == 4

    def test_custom_panes_per_window(self, fake_home: Path, tmp_path: Path) -> None:
        # 8 projects with panes_per_window=2 → 4 windows of 2 panes each.
        for i in range(8):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        created, messages = layout.ensure_session(panes_per_window=2)
        assert created
        assert not any("failed" in m for m in messages), messages

        names = _window_names(layout.SESSION)
        assert len(names) == 4
        for name in names:
            assert _pane_count(layout.SESSION, name) == 2

    def test_invalid_panes_per_window_rejected(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="panes_per_window"):
            layout.ensure_session(panes_per_window=0)


class TestActivePane:
    """After setup, attaching users should land on the orchestrator pane."""

    def _active(self, session: str) -> tuple[str, int]:
        r = tmux._run([
            "display-message", "-p", "-t", session,
            "-F", "#{window_name}:#{pane_index}",
        ])
        assert r.ok, r.stderr
        window, pane = r.stdout.strip().split(":")
        return window, int(pane)

    def test_orchestrator_is_active_pane_after_setup(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        # Orchestrator + 3 projects = 4 panes; last split normally leaves
        # pane 3 active, but we force focus back to pane 0.
        for i in range(3):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub")

        layout.ensure_session(orchestrator=orch)
        window, pane = self._active(layout.SESSION)
        assert window == layout.window_name(0, has_orchestrator=True)
        assert pane == 0

    def test_first_window_is_active_with_overflow(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        # Even when overflow windows exist, focus stays on the first one.
        for i in range(6):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        layout.ensure_session()
        window, pane = self._active(layout.SESSION)
        assert window == layout.window_name(0)
        assert pane == 0


class TestPaneTitlesAndStyle:
    """Pane border titles + orchestrator highlight."""

    def _pane_titles(self, window_target: str) -> list[str]:
        r = tmux._run([
            "list-panes", "-t", window_target,
            "-F", "#{pane_title}",
        ])
        assert r.ok
        return r.stdout.strip().splitlines()

    def test_project_panes_get_project_names_as_titles(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        for name in ("alpha", "beta"):
            d = tmp_path / name
            d.mkdir()
            registry.add_project(name, str(d), agent="shell")

        layout.ensure_session()
        titles = self._pane_titles(f"{layout.SESSION}:{layout.window_name(0)}")
        assert "alpha" in titles
        assert "beta" in titles

    def test_orchestrator_pane_title_has_marker(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        d = tmp_path / "proj"
        d.mkdir()
        registry.add_project("proj", str(d), agent="shell")

        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub")

        layout.ensure_session(orchestrator=orch)
        hub = layout.window_name(0, has_orchestrator=True)
        titles = self._pane_titles(f"{layout.SESSION}:{hub}")
        assert any("Central MCP Orchestrator" in t for t in titles)
        assert "proj" in titles

    def test_hub_row_panes_have_equal_widths(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        """0.6.3+: orchestrator no longer takes a forced 50% left column.
        On a wide terminal, orch + 2 projects land in a single row and
        every pane in that row has the same width (no main-vertical).
        """
        for i in range(2):
            d = tmp_path / f"p{i}"
            d.mkdir()
            registry.add_project(f"p{i}", str(d), agent="shell")

        orch_dir = tmp_path / "orch"
        orch_dir.mkdir()
        orch = layout.OrchestratorPane(command=":", cwd=str(orch_dir), label="stub")

        layout.ensure_session(orchestrator=orch)
        hub = layout.window_name(0, has_orchestrator=True)
        r = tmux._run([
            "list-panes", "-t", f"{layout.SESSION}:{hub}",
            "-F", "#{pane_index}:#{pane_left}:#{pane_width}:#{pane_top}",
        ])
        assert r.ok
        panes = []
        for line in r.stdout.strip().splitlines():
            idx, left, width, top = line.split(":")
            panes.append({
                "index": int(idx),
                "left": int(left),
                "width": int(width),
                "top": int(top),
            })
        assert len(panes) == 3
        # All three panes are on the same row → same `top` coord.
        tops = {p["top"] for p in panes}
        assert len(tops) == 1, f"panes not on the same row: {panes!r}"
        # Widths should be within 2 cells of each other — tmux rounds
        # each split to whole cells, and compounding rounding across
        # sequential splits can stretch the max/min by 1-2 cells even
        # with mathematically balanced percentages. Anything worse means
        # the size-percentage formula has regressed.
        widths = sorted(p["width"] for p in panes)
        assert widths[-1] - widths[0] <= 2, (
            f"row widths not equal: {widths!r}"
        )
