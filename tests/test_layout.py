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
