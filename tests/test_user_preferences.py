"""Tests for get_user_preferences and update_user_preferences MCP tools,
plus the pristine-template migration in `_ensure_launch_dir`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import central_mcp.server as srv
from central_mcp.cli._commands import _ensure_launch_dir, _is_pristine_user_md


def _write(fake_home: Path, filename: str, content: str) -> Path:
    fake_home.mkdir(parents=True, exist_ok=True)
    p = fake_home / filename
    p.write_text(content)
    return p


class TestGetUserPreferences:
    def test_returns_empty_when_file_missing(self, fake_home: Path) -> None:
        result = srv.get_user_preferences()
        assert result["ok"] is True
        assert result["content"] == ""
        assert result["is_empty"] is True

    def test_returns_file_content_when_present(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "## Reporting style\n\n- bullets\n")
        result = srv.get_user_preferences()
        assert result["ok"] is True
        assert "bullets" in result["content"]
        assert result["is_empty"] is False

    def test_carries_available_sections_and_examples(
        self, fake_home: Path
    ) -> None:
        result = srv.get_user_preferences()
        # available_sections lists every valid `section` argument.
        assert set(result["available_sections"]) == {
            "Reporting style",
            "Routing hints",
            "Process management rules",
            "Other preferences",
        }
        # examples are illustrative only — never written to user.md.
        assert "Reporting style" in result["examples"]
        assert isinstance(result["examples"]["Reporting style"], list)
        assert all(
            isinstance(line, str)
            for lines in result["examples"].values()
            for line in lines
        )


class TestUpdateUserPreferences:
    def test_creates_section_in_empty_file(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "")
        result = srv.update_user_preferences(
            section="Reporting style",
            content="- Always summarize in bullet points.",
        )
        assert result["ok"] is True
        text = (fake_home / "user.md").read_text()
        assert "## Reporting style" in text
        assert "Always summarize in bullet points." in text
        # updated_preferences carries the full file for mid-session re-apply
        assert "Always summarize in bullet points." in result["updated_preferences"]

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

        srv.update_user_preferences(
            section="Reporting style", content="- bullets only"
        )
        result2 = srv.get_user_preferences()
        assert "bullets only" in result2["content"]
        assert "English only" not in result2["content"]


class TestWriteUserMdSection:
    def test_handles_no_trailing_newline(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "## Reporting style\n\n- old")
        srv.update_user_preferences("Reporting style", "- new")
        text = (fake_home / "user.md").read_text()
        assert "new" in text
        assert "old" not in text


# ── Pristine-template migration (cli._commands._ensure_launch_dir) ────────────
#
# `_PRISTINE_0_10_11_TEMPLATE` is the exact byte content of the user.md
# that 0.10.11 and earlier scaffolded into ~/.central-mcp/. The migration
# in `_ensure_launch_dir` deletes byte-equal copies; tests pin the
# contract here. (Korean text below is intentional — it was part of the
# legacy template and must round-trip through the migration check.)

_PRISTINE_0_10_11_TEMPLATE = """# User preferences — central-mcp

This file is yours. Edit it to shape how the dispatch router behaves
in every session. The orchestrator reads it at startup and applies your
preferences on top of the shared defaults in AGENTS.md / CLAUDE.md.

Your settings here win over router defaults, but they do not override
developer constraints or system-level instructions. Your current-turn
instructions still take the highest priority.

---

## Reporting style

<!-- Examples — uncomment and edit what you want:

- Always summarize dispatch results in bullet points.
- Use Korean for all responses ("한국어로 답변해줘").
- Show elapsed time and token usage when reporting dispatch results.
- Keep responses under 5 sentences unless I ask for detail.

-->

## Routing hints

<!-- Examples:

- Prefer claude for any task involving architecture decisions.
- Use codex for shell-scripting tasks.
- Always dispatch UI work to the `my-frontend` project.

-->

## Process management rules

<!-- Examples:

- Never dispatch two tasks to the same project simultaneously.
- Ask before dispatching to more than 3 projects at once.

-->

## Other preferences

<!-- Anything else that affects how the router should behave. -->
"""


class TestIsPristineUserMd:
    def test_pristine_template_is_pristine(self) -> None:
        assert _is_pristine_user_md(_PRISTINE_0_10_11_TEMPLATE)

    def test_empty_file_is_pristine(self) -> None:
        assert _is_pristine_user_md("")

    def test_only_whitespace_is_pristine(self) -> None:
        assert _is_pristine_user_md("\n\n\n  \n")

    def test_modified_template_is_not_pristine(self) -> None:
        # Single-keystroke change — must NOT be classified as pristine.
        edited = _PRISTINE_0_10_11_TEMPLATE + "\n- one new rule\n"
        assert not _is_pristine_user_md(edited)

    def test_byte_difference_is_not_pristine(self) -> None:
        # Trailing whitespace is enough to fail the byte match — that's by
        # design (false positives are expensive: deleting user content).
        assert not _is_pristine_user_md(_PRISTINE_0_10_11_TEMPLATE + " ")


class TestEnsureLaunchDirMigration:
    def test_deletes_pristine_template(self, fake_home: Path) -> None:
        fake_home.mkdir(parents=True, exist_ok=True)
        user_md = fake_home / "user.md"
        user_md.write_text(_PRISTINE_0_10_11_TEMPLATE)
        _ensure_launch_dir(fake_home)
        assert not user_md.exists(), "pristine template should be removed"

    def test_preserves_user_authored_content(self, fake_home: Path) -> None:
        fake_home.mkdir(parents=True, exist_ok=True)
        user_md = fake_home / "user.md"
        edited = "## Reporting style\n\n- Always use bullets.\n"
        user_md.write_text(edited)
        _ensure_launch_dir(fake_home)
        assert user_md.exists()
        assert "Always use bullets." in user_md.read_text()

    def test_does_not_create_user_md_when_missing(self, fake_home: Path) -> None:
        user_md = fake_home / "user.md"
        assert not user_md.exists()
        _ensure_launch_dir(fake_home)
        assert not user_md.exists(), (
            "user.md should NOT be scaffolded — it's user-authored only"
        )


# ── _build_mcp_instructions never injects examples ────────────────────────────

class TestBuildMcpInstructions:
    def test_returns_base_when_user_md_missing(self, fake_home: Path) -> None:
        out = srv._build_mcp_instructions()
        assert "Your persistent preferences" not in out

    def test_returns_base_when_user_md_empty(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "")
        out = srv._build_mcp_instructions()
        assert "Your persistent preferences" not in out

    def test_returns_base_when_user_md_whitespace(self, fake_home: Path) -> None:
        _write(fake_home, "user.md", "   \n\n\t\n")
        out = srv._build_mcp_instructions()
        assert "Your persistent preferences" not in out

    def test_appends_when_user_authored_content(self, fake_home: Path) -> None:
        _write(
            fake_home,
            "user.md",
            "## Reporting style\n\n- Use bullet points everywhere.\n",
        )
        out = srv._build_mcp_instructions()
        assert "Your persistent preferences" in out
        assert "Use bullet points everywhere." in out
