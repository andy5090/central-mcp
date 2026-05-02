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


def test_unsupported_agent_rejected(capsys: pytest.CaptureFixture) -> None:
    rc = cmd_tui(_args(experimental=True, agent="codex"))
    assert rc == 2
    err = capsys.readouterr().err
    assert "codex" in err
    assert "claude only" in err.lower()


def test_missing_tui_extras_actionable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    # Force the lazy `from central_mcp.tui import app` to raise
    # ImportError — simulates a host without the [tui] extras.
    monkeypatch.setitem(sys.modules, "central_mcp.tui.app", None)

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
