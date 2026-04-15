from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def _resolve_default_registry() -> Path:
    """Pick the registry path using a three-level cascade.

    1. $CENTRAL_MCP_REGISTRY (explicit override)
    2. ./registry.yaml if it already exists in the current directory
       (dev-mode / per-project override)
    3. $HOME/.central-mcp/registry.yaml (global default for installed users)

    The returned path is always absolute. It may or may not exist yet — callers
    that write should `mkdir -p` its parent.
    """
    env = os.environ.get("CENTRAL_MCP_REGISTRY")
    if env:
        return Path(env).expanduser().resolve()
    cwd_candidate = Path.cwd() / "registry.yaml"
    if cwd_candidate.exists():
        return cwd_candidate.resolve()
    return (Path.home() / ".central-mcp" / "registry.yaml").resolve()


DEFAULT_REGISTRY_PATH = _resolve_default_registry()

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


@dataclass
class TmuxTarget:
    session: str
    window: str
    pane: int

    @property
    def target(self) -> str:
        return f"{self.session}:{self.window}.{self.pane}"


@dataclass
class Project:
    name: str
    path: str
    agent: str
    tmux: TmuxTarget
    description: str = ""
    tags: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "agent": self.agent,
            "tmux_target": self.tmux.target,
            "description": self.description,
            "tags": self.tags or [],
        }


def _read_raw(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open() as f:
        return _yaml.load(f) or {}


def _write_raw(data: dict[str, Any], path: Path = DEFAULT_REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        _yaml.dump(data, f)


def _project_from_raw(p: dict[str, Any]) -> Project:
    tmux_raw = p.get("tmux") or {}
    return Project(
        name=p["name"],
        path=p["path"],
        agent=p.get("agent", "shell"),
        tmux=TmuxTarget(
            session=tmux_raw.get("session", "central"),
            window=tmux_raw.get("window", "projects"),
            pane=int(tmux_raw.get("pane", 0)),
        ),
        description=p.get("description", ""),
        tags=list(p.get("tags") or []),
    )


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> list[Project]:
    data = _read_raw(path)
    return [_project_from_raw(p) for p in (data.get("projects") or [])]


def find_project(name: str, path: Path = DEFAULT_REGISTRY_PATH) -> Project | None:
    for p in load_registry(path):
        if p.name == name:
            return p
    return None


def add_project(
    name: str,
    path_: str,
    agent: str = "shell",
    session: str = "central",
    window: str = "projects",
    pane: int | None = None,
    description: str = "",
    tags: list[str] | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> Project:
    """Append a project to registry.yaml. Returns the created Project.

    Raises ValueError if a project with the same name already exists.
    If pane is None, auto-assigns the next free index within (session, window).
    """
    data = _read_raw(registry_path)
    projects = data.get("projects") or []

    if any((p.get("name") == name) for p in projects):
        raise ValueError(f"project {name!r} already exists")

    if pane is None:
        used = [
            int((p.get("tmux") or {}).get("pane", -1))
            for p in projects
            if (p.get("tmux") or {}).get("session") == session
            and (p.get("tmux") or {}).get("window") == window
        ]
        pane = (max(used) + 1) if used else 0

    entry: dict[str, Any] = {
        "name": name,
        "path": path_,
        "agent": agent,
        "tmux": {"session": session, "window": window, "pane": pane},
        "description": description,
        "tags": list(tags or []),
    }
    projects.append(entry)
    data["projects"] = projects
    _write_raw(data, registry_path)
    return _project_from_raw(entry)


def remove_project(
    name: str,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> bool:
    """Remove a project from registry.yaml. Returns True if something was removed."""
    data = _read_raw(registry_path)
    projects = data.get("projects") or []
    before = len(projects)
    projects = [p for p in projects if p.get("name") != name]
    if len(projects) == before:
        return False
    data["projects"] = projects
    _write_raw(data, registry_path)
    return True


def projects_by_session(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, list[Project]]:
    out: dict[str, list[Project]] = {}
    for p in load_registry(path):
        out.setdefault(p.tmux.session, []).append(p)
    return out
