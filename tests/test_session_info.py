"""Tests for the session-info version-stamp module.

Covers the three public entrypoints (`write`, `read`, `clear`) —
a stamp round-trips through disk, malformed files return None, and
a cleared stamp plus a fresh write returns to an in-sync state.
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


def test_write_accepts_explicit_version(fake_home: Path) -> None:
    session_info.write(multiplexer="tmux", version="9.9.9")
    stamp = session_info.read()
    assert stamp.version == "9.9.9"
