"""Contract tests for `cmcp tui --experimental` opt-out paths.

The TUI itself (textual app, PTY widget, watcher) is integration-tested
manually — too environment-dependent to unit-test reliably. What lives
here is the CLI's user-facing contract:

  1. Without --experimental, exit 2 with a hint pointing at the flag.
  2. With --experimental but the [tui] extras missing, exit 2 with a
     `pip install 'central-mcp[tui]'` hint.
  3. With an unsupported agent, exit 2 with a hint about claude-only.

Both extras-missing and extras-installed environments need to pass —
the test patches `sys.modules` to force ImportError so the path is
exercised even on a dev machine that has textual installed.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from central_mcp.cli._commands import cmd_tui


def _args(**overrides) -> SimpleNamespace:
    base = {"experimental": False, "agent": "claude"}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_requires_experimental_flag(capsys: pytest.CaptureFixture) -> None:
    rc = cmd_tui(_args(experimental=False))
    assert rc == 2
    err = capsys.readouterr().err
    assert "--experimental" in err
    assert "experimental" in err.lower()


@pytest.mark.parametrize("agent", ["gemini", "opencode", "droid", "totally-fake"])
def test_unsupported_agent_rejected(
    agent: str, capsys: pytest.CaptureFixture
) -> None:
    rc = cmd_tui(_args(experimental=True, agent=agent))
    assert rc == 2
    err = capsys.readouterr().err
    assert agent in err
    # Lists every currently supported agent so the user knows what to retry.
    assert "claude" in err
    assert "codex" in err


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_supported_agents_pass_gate(
    agent: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent allowlist must include both claude and codex (Phase B).

    We stub `tui.app.run_tui` so the test doesn't actually spawn the
    agent's PTY child — only verifies cmd_tui's gate accepts the agent
    and forwards it through.
    """
    pytest.importorskip("textual", reason="[tui] extras not installed")
    from central_mcp.tui import app as tui_app

    captured: dict[str, str] = {}
    def _fake_run_tui(agent: str = "claude") -> int:
        captured["agent"] = agent
        return 0
    monkeypatch.setattr(tui_app, "run_tui", _fake_run_tui)

    rc = cmd_tui(_args(experimental=True, agent=agent))
    assert rc == 0
    assert captured["agent"] == agent


def test_missing_tui_extras_actionable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    # Force the lazy `from central_mcp.tui import app` to raise
    # ImportError — simulates a host without the [tui] extras.
    # Both knobs are required: an earlier test in the suite may have
    # already imported `central_mcp.tui.app` and bound it as an
    # attribute on the parent package, in which case `from
    # central_mcp.tui import app` resolves via attribute lookup before
    # consulting sys.modules.
    monkeypatch.setitem(sys.modules, "central_mcp.tui.app", None)
    import central_mcp.tui as _tui_pkg
    monkeypatch.delattr(_tui_pkg, "app", raising=False)

    rc = cmd_tui(_args(experimental=True, agent="claude"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "central-mcp[tui]" in err
    assert "pip install" in err


def test_errors_module_helpers(capsys: pytest.CaptureFixture) -> None:
    """Helpers themselves return 2 and write to stderr — used elsewhere
    if a future caller wants the same hints without going through the
    CLI."""
    from central_mcp.tui import errors

    assert errors.print_experimental_required() == 2
    err = capsys.readouterr().err
    assert "--experimental" in err

    assert errors.print_missing_extras(detail="No module named 'textual'") == 2
    err = capsys.readouterr().err
    assert "central-mcp[tui]" in err
    assert "No module named 'textual'" in err


def test_app_composes_headless() -> None:
    """Regression: catch textual API drift early.

    Headless Pilot run must mount Header / Sidebar / TokenHud /
    DispatchList / PtyTerminal / Footer without raising. A previous
    failure mode was `DispatchList._render` shadowing
    `textual.Widget._render` and returning a str into textual's
    layout pipeline, which exploded with `'str' object has no
    attribute 'get_height'`. This test fails fast if a future textual
    upgrade or refactor reintroduces a similar collision.
    """
    pytest.importorskip("textual", reason="[tui] extras not installed")
    pytest.importorskip("pyte", reason="[tui] extras not installed")
    import asyncio

    from central_mcp.tui import app as tui_app

    async def _run() -> set[str]:
        inst = tui_app.CentralMcpTUI(agent="claude")
        async with inst.run_test(headless=True, size=(120, 40)) as pilot:
            await pilot.pause()
            names = {c.__class__.__name__ for c in inst.query()}
            await pilot.press("ctrl+q")
            return names

    names = asyncio.run(_run())
    for required in ("Header", "Sidebar", "TokenHud", "DispatchList", "PtyTerminal", "Footer"):
        assert required in names, f"missing widget {required!r} in {names}"


def test_submit_prompt_without_project_writes_bytes_only(
    fake_home, capsys: pytest.CaptureFixture
) -> None:
    """A free-floating PTY (no project bound) writes the prompt to its
    master fd but creates no `dispatches.db` row. This is the path used
    when the TUI hosts the orchestrator's own claude REPL — that
    session isn't a project dispatch, so it shouldn't leak into the
    sidebar's running list.
    """
    pytest.importorskip("pyte")
    import pty as _pty
    from central_mcp import dispatches_db
    from central_mcp.tui.terminal import PtyTerminal

    master, slave = _pty.openpty()
    try:
        term = PtyTerminal(["claude"])  # no project= → tracking disabled
        term._master_fd = master

        did = term.submit_prompt("hello world")
        assert did is None

        os.set_blocking(slave, False)
        seen = b""
        try:
            while True:
                chunk = os.read(slave, 4096)
                if not chunk:
                    break
                seen += chunk
        except (BlockingIOError, OSError):
            pass
        assert b"hello world" in seen

        assert dispatches_db.list_all() == []
    finally:
        os.close(master)
        os.close(slave)


def test_submit_prompt_with_project_records_dispatch(fake_home) -> None:
    """When bound to a project, submit_prompt() writes a `running` row
    to dispatches.db and a `start` event to dispatch.jsonl — the same
    surfaces the MCP `dispatch()` tool writes to. DispatchWatcher's
    sidebar refresh path treats both writers identically.
    """
    pytest.importorskip("pyte")
    import pty as _pty
    from central_mcp import dispatches_db, events as ev
    from central_mcp.tui.terminal import PtyTerminal

    master, slave = _pty.openpty()
    try:
        term = PtyTerminal(["claude"], project="my-app", agent="claude")
        term._master_fd = master

        did = term.submit_prompt("explain this codebase")
        assert did is not None and len(did) == 8
        assert term._active_did == did

        rows = dispatches_db.list_all()
        assert len(rows) == 1
        entry = rows[0]
        assert entry["id"] == did
        assert entry["project"] == "my-app"
        assert entry["agent"] == "claude"
        assert entry["status"] == "running"
        assert entry["prompt"] == "explain this codebase"

        log = ev.log_path("my-app").read_text().strip().splitlines()
        assert len(log) == 1
        import json as _json
        rec = _json.loads(log[0])
        assert rec["event"] == "start"
        assert rec["mode"] == "pty"
        assert rec["prompt"] == "explain this codebase"
    finally:
        os.close(master)
        os.close(slave)


def test_submit_prompt_does_not_double_track_while_active(fake_home) -> None:
    """A second submit_prompt() while a dispatch is still in flight
    writes the bytes (so the user can answer follow-up questions) but
    does not start a second tracking record."""
    pytest.importorskip("pyte")
    import pty as _pty
    from central_mcp import dispatches_db
    from central_mcp.tui.terminal import PtyTerminal

    master, slave = _pty.openpty()
    try:
        term = PtyTerminal(["claude"], project="my-app", agent="claude")
        term._master_fd = master

        first = term.submit_prompt("question one")
        assert first is not None
        second = term.submit_prompt("yes please continue")
        assert second is None  # already active — no new tracking

        rows = dispatches_db.list_all()
        assert len(rows) == 1
        assert rows[0]["id"] == first
    finally:
        os.close(master)
        os.close(slave)


def test_screen_hash_changes_with_content() -> None:
    """The completion watcher's signal: hash flips when bottom-row
    bytes change, holds steady otherwise."""
    pyte = pytest.importorskip("pyte")
    from central_mcp.tui.terminal import PtyTerminal

    term = PtyTerminal(["claude"])
    term._screen = pyte.Screen(80, 24)
    term._stream = pyte.ByteStream(term._screen)

    h0 = term._screen_hash()
    term._stream.feed(b"hello world\r\n")
    h1 = term._screen_hash()
    assert h0 != h1
    # No new bytes → identical hash, which is the signal the watcher
    # uses to count `_STABLE_TICKS` toward completion.
    assert term._screen_hash() == h1


def test_mark_complete_writes_finished_row(fake_home) -> None:
    """_mark_complete() updates the dispatches.db row to a terminal
    state and emits the matching `complete` event into dispatch.jsonl.
    """
    pytest.importorskip("pyte")
    import time as _time
    from central_mcp import dispatches_db, events as ev
    from central_mcp.tui.terminal import PtyTerminal

    term = PtyTerminal(["claude"], project="my-app", agent="claude")
    term._active_did = "abcd1234"
    term._active_started_at = _time.time() - 2.5
    dispatches_db.upsert_started({
        "id": "abcd1234",
        "project": "my-app",
        "agent": "claude",
        "status": "running",
        "started": term._active_started_at,
        "prompt": "hi",
        "command": "claude",
        "chain": ["claude"],
    })

    term._mark_complete(ok=True, status="complete")

    rows = dispatches_db.list_all()
    assert len(rows) == 1
    entry = rows[0]
    assert entry["status"] == "complete"
    assert entry["result"]["ok"] is True
    assert entry["result"]["duration_sec"] >= 2.0
    assert term._active_did is None

    log = ev.log_path("my-app").read_text().strip().splitlines()
    import json as _json
    events_recorded = [_json.loads(line)["event"] for line in log]
    assert "complete" in events_recorded


def test_private_csi_leak_filter_strips_kitty_keyboard_queries() -> None:
    """Regression: claude probes terminal capabilities with Kitty keyboard
    protocol / xterm extended queries (`\\x1b[<u`, `\\x1b[>1u`,
    `\\x1b[>4;2m`, `\\x1b[>0q`). pyte 0.8.2's CSI parser bails on the
    `<` / `>` private-prefix bytes and leaks the final byte (typically
    `u`) into the screen as a literal — that's the visible "u" that
    used to stick on the first line of the embedded REPL. Strip those
    sequences before pyte sees them.
    """
    pytest.importorskip("pyte", reason="[tui] extras not installed")
    from central_mcp.tui.terminal import _PRIVATE_CSI_LEAK_RE

    leaky = (
        b"\x1b[<u"        # kitty pop keyboard mode
        b"\x1b[>1u"       # kitty push keyboard mode
        b"\x1b[>4;2m"    # xterm modify-other-keys
        b"\x1b[>0q"      # xterm extended cursor-style query
        b"hello"
    )
    assert _PRIVATE_CSI_LEAK_RE.sub(b"", leaky) == b"hello"

    # Standard CSI sequences pyte handles must NOT be touched.
    keep = (
        b"\x1b[?25h"       # show cursor
        b"\x1b[?2026h"    # synchronized output
        b"\x1b[38;2;215;119;87m"  # truecolor fg
        b"\x1b[c"          # primary device attributes (DA1) — pyte handles
        b"\x1b[H"          # cursor home
        b"\x1b[2K"         # erase line
        b"text"
    )
    assert _PRIVATE_CSI_LEAK_RE.sub(b"", keep) == keep
