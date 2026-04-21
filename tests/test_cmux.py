"""Tests for the cmux observation backend.

Unit tests exercise `build_layout_json` (pure function, no subprocess)
plus `has_workspace` / `ensure_workspace` / `kill_workspace` with a
monkey-patched `_run` so we don't need a live cmux.app. A small test
also verifies that `_detect_multiplexers()` only offers `cmux` on
darwin — on Linux / Windows the backend should stay invisible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from central_mcp import cmux, registry
from central_mcp.layout import OrchestratorPane


def _make_projects(fake_home: Path, tmp_path: Path, n: int) -> None:
    for i in range(n):
        d = tmp_path / f"p{i}"
        d.mkdir()
        registry.add_project(f"p{i}", str(d), agent="shell")


def _collect_surfaces(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk a CmuxLayoutNode subtree, return every terminal surface leaf.

    Mirrors the schema: pane leaves live at `node["pane"]["surfaces"]`,
    split nodes have exactly two entries in `node["children"]`.
    """
    if "pane" in node:
        return list(node["pane"]["surfaces"])
    out: list[dict[str, Any]] = []
    for child in node.get("children", []):
        if isinstance(child, dict):
            out.extend(_collect_surfaces(child))
    return out


class TestBuildLayoutJson:
    """Asserts the layout subtree matches cmux's `CmuxLayoutNode`
    schema (see Sources/CmuxConfig.swift in manaflow-ai/cmux):

      - Pane leaf: `{"pane": {"surfaces": [...]}}`
      - Split node: `{"direction": "...", "split": 0.1-0.9,
        "children": [left, right]}` — exactly two children, no
        `first`/`second` keys.

    `build_layout_json` returns just the subtree (not the full
    `CmuxWorkspaceDefinition`) — the CLI forwards it as
    `params["layout"]` on `workspace.create`; title / cwd are passed
    on separate `--name` / `--cwd` flags.
    """

    def test_empty_registry_no_orchestrator_single_placeholder(
        self, fake_home: Path
    ) -> None:
        out = cmux.build_layout_json(None, registry.load_registry())
        assert out == {"pane": {"surfaces": [{"type": "terminal", "focus": True}]}}

    def test_result_is_bare_layout_subtree_no_workspace_wrapper(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        """The returned dict must decode as `CmuxLayoutNode` directly —
        no enclosing `{name, cwd, layout}` wrapper (that would be a
        `CmuxWorkspaceDefinition`, which the v2 decoder rejects)."""
        orch = OrchestratorPane(command="claude", cwd=str(tmp_path), label="stub")
        out = cmux.build_layout_json(orch, [])
        assert "name" not in out
        assert "cwd" not in out
        assert "layout" not in out
        # Must have either `pane` (leaf) or `direction` (split) at root.
        assert ("pane" in out) ^ ("direction" in out)

    def test_orchestrator_only_is_single_pane_leaf(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        orch = OrchestratorPane(command="claude", cwd=str(tmp_path), label="stub")
        out = cmux.build_layout_json(orch, [])
        # Leaf: pane key present, direction absent.
        assert "pane" in out
        assert "direction" not in out
        surfaces = out["pane"]["surfaces"]
        assert len(surfaces) == 1
        s = surfaces[0]
        assert s["type"] == "terminal"
        assert s["name"] == "Central MCP Orchestrator"
        assert s["cwd"] == str(tmp_path)
        assert s["focus"] is True
        # Orchestrator command is wrapped so the pane survives exit.
        assert s["command"] == "claude; exec $SHELL"

    def test_orchestrator_plus_one_project_splits_horizontally(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        _make_projects(fake_home, tmp_path, 1)
        orch = OrchestratorPane(command="claude", cwd=str(tmp_path), label="stub")
        layout = cmux.build_layout_json(orch, registry.load_registry())
        assert layout["direction"] == "horizontal"
        assert layout["split"] == 0.5
        # Split node has exactly two entries under `children`.
        assert "children" in layout
        assert "first" not in layout
        assert "second" not in layout
        assert len(layout["children"]) == 2
        # Left: orchestrator pane.
        left_surfaces = _collect_surfaces(layout["children"][0])
        assert len(left_surfaces) == 1
        assert left_surfaces[0]["name"] == "Central MCP Orchestrator"
        assert left_surfaces[0]["focus"] is True
        # Right: the single project pane (one surface, readonly-wrapped).
        right_surfaces = _collect_surfaces(layout["children"][1])
        assert len(right_surfaces) == 1
        proj = right_surfaces[0]
        assert proj["name"] == "p0"
        assert "central-mcp watch p0" in proj["command"]
        assert "</dev/null" in proj["command"]
        assert "sleep infinity" in proj["command"]
        # Project panes are not focused — orchestrator is.
        assert proj.get("focus") is not True

    def test_orchestrator_plus_four_projects_uses_two_row_grid(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        _make_projects(fake_home, tmp_path, 4)
        orch = OrchestratorPane(command="claude", cwd=str(tmp_path), label="stub")
        layout = cmux.build_layout_json(orch, registry.load_registry())
        # Outer split: orchestrator on left, projects subtree on right.
        assert layout["direction"] == "horizontal"
        right = layout["children"][1]
        # Project subtree for n=4 is a 2-row grid: outer vertical split
        # (row1 / row2), each row is a horizontal cascade.
        assert right["direction"] == "vertical"
        assert len(right["children"]) == 2
        # Leaves on the right side should cover all four projects.
        right_surfaces = _collect_surfaces(right)
        names = sorted(s["name"] for s in right_surfaces)
        assert names == ["p0", "p1", "p2", "p3"]
        # Every project pane carries the readonly wrap.
        for s in right_surfaces:
            assert "central-mcp watch" in s["command"]
            assert "sleep infinity" in s["command"]

    def test_every_split_has_exactly_two_children(self, tmp_path: Path) -> None:
        """cmux's `CmuxSplitDefinition` decoder explicitly rejects
        anything other than 2 children — verify the tiler never emits
        a degenerate split, for any project count 1..8."""
        from central_mcp.registry import Project as P

        for n in range(1, 9):
            projects = [P(name=f"p{i}", path=str(tmp_path)) for i in range(n)]
            orch = OrchestratorPane(command="claude", cwd=str(tmp_path), label="stub")
            layout = cmux.build_layout_json(orch, projects)

            def walk(node: dict[str, Any]) -> None:
                if "direction" in node:
                    assert len(node["children"]) == 2, (
                        f"n={n}: split has {len(node['children'])} children"
                    )
                    for c in node["children"]:
                        walk(c)

            walk(layout)

    def test_projects_only_first_surface_gets_focus(
        self, fake_home: Path, tmp_path: Path
    ) -> None:
        _make_projects(fake_home, tmp_path, 3)
        layout = cmux.build_layout_json(None, registry.load_registry())
        surfaces = _collect_surfaces(layout)
        focused = [s for s in surfaces if s.get("focus") is True]
        assert len(focused) == 1
        # The first project pane (p0) lands the user on project 0.
        assert focused[0]["name"] == "p0"


# ---------- subprocess-mocked behavioral tests ----------

class _FakeRun:
    """Records calls and returns canned CmuxResult-like objects."""

    def __init__(self, responses: list[cmux.CmuxResult]) -> None:
        self.calls: list[list[str]] = []
        self._responses = list(responses)

    def __call__(self, args: list[str]) -> cmux.CmuxResult:
        self.calls.append(list(args))
        if not self._responses:
            return cmux.CmuxResult(ok=True, stdout="", stderr="")
        return self._responses.pop(0)


class TestHasWorkspace:
    def test_true_when_workspace_titled_central_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "w1", "title": cmux.SESSION, "ref": "workspace:0"}]}
        )
        fake = _FakeRun([cmux.CmuxResult(ok=True, stdout=payload, stderr="")])
        monkeypatch.setattr(cmux, "_run", fake)
        assert cmux.has_workspace(cmux.SESSION) is True
        # --json is a GLOBAL flag — must come before the subcommand.
        assert fake.calls == [["--json", "list-workspaces"]]

    def test_false_when_no_matching_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "w1", "title": "something-else"}]}
        )
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=True, stdout=payload, stderr="")]),
        )
        assert cmux.has_workspace(cmux.SESSION) is False

    def test_false_when_list_command_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=False, stdout="", stderr="boom")]),
        )
        assert cmux.has_workspace(cmux.SESSION) is False

    def test_false_when_output_is_not_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=True, stdout="not json", stderr="")]),
        )
        assert cmux.has_workspace(cmux.SESSION) is False


class TestEnsureWorkspace:
    def test_no_op_when_workspace_already_open(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "w1", "title": cmux.SESSION}]}
        )
        fake = _FakeRun([cmux.CmuxResult(ok=True, stdout=payload, stderr="")])
        monkeypatch.setattr(cmux, "_run", fake)
        created, messages = cmux.ensure_workspace()
        assert created is False
        assert any("already exists" in m for m in messages)
        # Only the probe call — no new-workspace was issued.
        assert fake.calls == [["--json", "list-workspaces"]]

    def test_creates_workspace_when_missing(
        self, fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_projects(fake_home, tmp_path, 2)
        # Sequence: list-workspaces (empty) → new-workspace (ok).
        empty = json.dumps({"workspaces": []})
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=empty, stderr=""),
            cmux.CmuxResult(ok=True, stdout="", stderr=""),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        orch = OrchestratorPane(command="claude", cwd=str(tmp_path), label="stub")
        created, messages = cmux.ensure_workspace(orchestrator=orch)
        assert created is True
        assert any("opened via cmux" in m for m in messages)
        # Second call is `new-workspace --name central --layout <json>`.
        assert len(fake.calls) == 2
        new_call = fake.calls[1]
        # Title goes on --name, so the CLI forwards it as a separate
        # `title` param; the --layout value is the bare CmuxLayoutNode
        # subtree the server will decode directly.
        assert new_call[:4] == ["new-workspace", "--name", cmux.SESSION, "--layout"]
        layout = json.loads(new_call[4])
        assert "name" not in layout  # not a CmuxWorkspaceDefinition
        assert "layout" not in layout  # bare subtree, not nested
        assert layout["direction"] == "horizontal"
        assert "children" in layout and len(layout["children"]) == 2

    def test_surfaces_stderr_on_new_workspace_failure(
        self, fake_home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = json.dumps({"workspaces": []})
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=empty, stderr=""),
            cmux.CmuxResult(ok=False, stdout="", stderr="socket refused"),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        created, messages = cmux.ensure_workspace()
        assert created is False
        assert any("socket refused" in m for m in messages)


class TestKillWorkspace:
    def test_noop_when_nothing_to_kill(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = json.dumps({"workspaces": []})
        monkeypatch.setattr(
            cmux, "_run",
            _FakeRun([cmux.CmuxResult(ok=True, stdout=empty, stderr="")]),
        )
        r = cmux.kill_workspace(cmux.SESSION)
        assert r.ok is True
        assert "no workspace" in r.stderr

    def test_uses_ref_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [
                {"id": "uuid-1", "title": cmux.SESSION, "ref": "workspace:0"},
            ]}
        )
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=payload, stderr=""),
            cmux.CmuxResult(ok=True, stdout="", stderr=""),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        r = cmux.kill_workspace(cmux.SESSION)
        assert r.ok is True
        # Second call should be close-workspace with the ref form.
        assert fake.calls[1] == ["close-workspace", "--workspace", "workspace:0"]

    def test_falls_back_to_id_when_no_ref(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = json.dumps(
            {"workspaces": [{"id": "uuid-1", "title": cmux.SESSION}]}
        )
        fake = _FakeRun([
            cmux.CmuxResult(ok=True, stdout=payload, stderr=""),
            cmux.CmuxResult(ok=True, stdout="", stderr=""),
        ])
        monkeypatch.setattr(cmux, "_run", fake)
        cmux.kill_workspace(cmux.SESSION)
        assert fake.calls[1] == ["close-workspace", "--workspace", "uuid-1"]


# ---------- platform gating ----------

class TestDetectMultiplexersPlatformGating:
    """`cmux` is macOS-only — confirm `_detect_multiplexers` only offers
    it on darwin even when the binary happens to be on PATH."""

    def test_cmux_excluded_on_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.cli import _commands

        monkeypatch.setattr(_commands.platform, "system", lambda: "Linux")
        monkeypatch.setattr(_commands.shutil, "which", lambda _b: "/fake/bin")
        names = [name for name, _bin in _commands._detect_multiplexers()]
        assert "cmux" not in names
        assert "tmux" in names
        assert "zellij" in names

    def test_cmux_included_on_darwin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from central_mcp.cli import _commands

        monkeypatch.setattr(_commands.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(_commands.shutil, "which", lambda _b: "/fake/bin")
        names = [name for name, _bin in _commands._detect_multiplexers()]
        assert "cmux" in names
