"""Tests for the session-info version-stamp module.

Covers the four public entrypoints (`write`, `read`, `clear`,
`staleness_warning`) plus their interaction — a stamp round-trips
through disk, a version bump produces a warning, and a cleared stamp
plus a fresh write returns to an in-sync state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from central_mcp import paths, session_info


def test_write_then_read_roundtrip(fake_home: Path) -> None:
    session_info.write(multiplexer="tmux", version="0.6.0")
    stamp = session_info.read()
    assert stamp is not None
    assert stamp.version == "0.6.0"
    assert stamp.multiplexer == "tmux"
    assert stamp.created_at  # non-empty ISO timestamp


def test_read_missing_returns_none(fake_home: Path) -> None:
    # No write() has been called yet.
    assert session_info.read() is None


def test_read_malformed_returns_none(fake_home: Path) -> None:
    paths.session_info_file().parent.mkdir(parents=True, exist_ok=True)
    paths.session_info_file().write_text("not = toml = really {")
    assert session_info.read() is None


def test_clear_removes_the_file(fake_home: Path) -> None:
    session_info.write(multiplexer="zellij", version="0.6.0")
    assert paths.session_info_file().exists()
    session_info.clear()
    assert not paths.session_info_file().exists()
    # Clearing again is a no-op, not an error.
    session_info.clear()


def test_staleness_warning_none_for_missing_stamp() -> None:
    # Legacy sessions (no stamp file) are treated as "fresh enough".
    assert session_info.staleness_warning(None) is None


def test_staleness_warning_none_when_versions_match(fake_home: Path) -> None:
    session_info.write(multiplexer="tmux", version="0.6.0")
    stamp = session_info.read()
    assert session_info.staleness_warning(stamp, now="0.6.0") is None


def test_staleness_warning_flags_mismatch(fake_home: Path) -> None:
    session_info.write(multiplexer="zellij", version="0.5.2")
    stamp = session_info.read()
    warning = session_info.staleness_warning(stamp, now="0.6.0")
    assert warning is not None
    assert "0.5.2" in warning
    assert "0.6.0" in warning
    # Warning must suggest the multiplexer the session was built for
    # so the user knows which `cmcp` command to re-run.
    assert "zellij" in warning


def test_write_accepts_explicit_version(fake_home: Path) -> None:
    session_info.write(multiplexer="tmux", version="9.9.9")
    stamp = session_info.read()
    assert stamp.version == "9.9.9"
