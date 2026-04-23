"""Tests for get_user_preferences and update_user_preferences MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest

import central_mcp.server as srv


def _write(fake_home: Path, filename: str, content: str) -> Path:
    fake_home.mkdir(parents=True, exist_ok=True)
    p = fake_home / filename
    p.write_text(content)
    return p


class TestGetUserPreferences:
    def test_returns_empty_when_file_missing(self, fake_home: Path) -> None:
        result = srv.get_user_preferences()
        assert result["ok"] is True
        assert result["content"] == "(empty)"

    def test_returns_file_content_when_present(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "## Reporting style\n\n- bullets\n")
        result = srv.get_user_preferences()
        assert result["ok"] is True
        assert "bullets" in result["content"]


class TestUpdateUserPreferences:
    def test_creates_section_in_empty_file(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "")
        result = srv.update_user_preferences(
            section="Reporting style",
            content="- 한국어로 답변할 것.",
        )
        assert result["ok"] is True
        text = (fake_home / "user.md").read_text()
        assert "## Reporting style" in text
        assert "한국어로 답변할 것." in text

    def test_replaces_existing_section(self, fake_home: Path) -> None:
        _write(
            fake_home, "user.md",
            "## Reporting style\n\n- old preference\n\n## Routing hints\n\n- keep this\n",
        )
        srv.update_user_preferences(section="Reporting style", content="- new preference")
        text = (fake_home / "user.md").read_text()
        assert "new preference" in text
        assert "old preference" not in text
        assert "keep this" in text  # other sections untouched

    def test_appends_new_section_to_existing_file(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "## Reporting style\n\n- bullets\n")
        srv.update_user_preferences(
            section="Routing hints",
            content="- prefer claude for architecture",
        )
        text = (fake_home / "user.md").read_text()
        assert "## Routing hints" in text
        assert "prefer claude for architecture" in text
        assert "bullets" in text  # original section intact

    def test_rejects_unknown_section(self, fake_home: Path) -> None:
        result = srv.update_user_preferences(section="Invalid section", content="whatever")
        assert result["ok"] is False
        assert "unknown section" in result["error"]

    def test_creates_file_if_missing(self, fake_home: Path) -> None:
        assert not (fake_home / "user.md").exists()
        result = srv.update_user_preferences(section="Other preferences", content="- test")
        assert result["ok"] is True
        assert (fake_home / "user.md").exists()

    def test_roundtrip_get_then_update(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "## Reporting style\n\n- English only\n")
        assert "English only" in srv.get_user_preferences()["content"]

        srv.update_user_preferences(section="Reporting style", content="- 한국어로 답변")
        result2 = srv.get_user_preferences()
        assert "한국어로 답변" in result2["content"]
        assert "English only" not in result2["content"]


class TestWriteUserMdSection:
    def test_handles_no_trailing_newline(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "## Reporting style\n\n- old")
        srv.update_user_preferences("Reporting style", "- new")
        text = (fake_home / "user.md").read_text()
        assert "new" in text
        assert "old" not in text
