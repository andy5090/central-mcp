from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from central_mcp import paths


def _default_path() -> Path:
    return paths.registry_path()


DEFAULT_REGISTRY_PATH = _default_path()

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)


@dataclass
class Project:
    name: str
    path: str
    agent: str = "claude"
    description: str = ""
    tags: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "agent": self.agent,
            "description": self.description,
            "tags": self.tags or [],
        }


def _read_raw(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = _default_path()
    if not path.exists():
        return {}
    with path.open() as f:
        return _yaml.load(f) or {}


def _write_raw(data: dict[str, Any], path: Path | None = None) -> None:
    if path is None:
        path = _default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        _yaml.dump(data, f)


def _project_from_raw(p: dict[str, Any]) -> Project:
    return Project(
        name=p["name"],
        path=p["path"],
        agent=p.get("agent", "claude"),
        description=p.get("description", ""),
        tags=list(p.get("tags") or []),
    )


def load_registry(path: Path | None = None) -> list[Project]:
    data = _read_raw(path)
    return [_project_from_raw(p) for p in (data.get("projects") or [])]


def find_project(name: str, path: Path | None = None) -> Project | None:
    for p in load_registry(path):
        if p.name == name:
            return p
    return None


def add_project(
    name: str,
    path_: str,
    agent: str = "claude",
    description: str = "",
    tags: list[str] | None = None,
    registry_path: Path | None = None,
) -> Project:
    """Append a project to registry.yaml. Raises ValueError on duplicate."""
    data = _read_raw(registry_path)
    projects = data.get("projects") or []

    if any((p.get("name") == name) for p in projects):
        raise ValueError(f"project {name!r} already exists")

    entry: dict[str, Any] = {
        "name": name,
        "path": path_,
        "agent": agent,
        "description": description,
        "tags": list(tags or []),
    }
    projects.append(entry)
    data["projects"] = projects
    _write_raw(data, registry_path)
    return _project_from_raw(entry)


def remove_project(
    name: str,
    registry_path: Path | None = None,
) -> bool:
    data = _read_raw(registry_path)
    projects = data.get("projects") or []
    before = len(projects)
    projects = [p for p in projects if p.get("name") != name]
    if len(projects) == before:
        return False
    data["projects"] = projects
    _write_raw(data, registry_path)
    return True
