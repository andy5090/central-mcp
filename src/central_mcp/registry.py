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
    bypass: bool | None = None  # None = not yet decided
    fallback: list[str] | None = None  # agents to try if primary fails

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "agent": self.agent,
            "description": self.description,
            "tags": self.tags or [],
            "bypass": self.bypass,
            "fallback": self.fallback or [],
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
    raw_bypass = p.get("bypass")
    raw_fallback = p.get("fallback")
    return Project(
        name=p["name"],
        path=p["path"],
        agent=p.get("agent", "claude"),
        description=p.get("description", ""),
        tags=list(p.get("tags") or []),
        bypass=bool(raw_bypass) if raw_bypass is not None else None,
        fallback=list(raw_fallback) if raw_fallback else None,
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


def update_project_bypass(
    name: str,
    bypass: bool,
    registry_path: Path | None = None,
) -> bool:
    """Set the bypass preference for an existing project. Returns True if found."""
    data = _read_raw(registry_path)
    projects = data.get("projects") or []
    for p in projects:
        if p.get("name") == name:
            p["bypass"] = bypass
            _write_raw(data, registry_path)
            return True
    return False


def update_project(
    name: str,
    *,
    agent: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    bypass: bool | None = None,
    fallback: list[str] | None = None,
    registry_path: Path | None = None,
) -> Project | None:
    """Update fields of an existing project. Omitted args stay unchanged.

    Returns the updated Project, or None if no project with `name` exists.
    """
    data = _read_raw(registry_path)
    projects = data.get("projects") or []
    for p in projects:
        if p.get("name") == name:
            if agent is not None:
                p["agent"] = agent
            if description is not None:
                p["description"] = description
            if tags is not None:
                p["tags"] = list(tags)
            if bypass is not None:
                p["bypass"] = bypass
            if fallback is not None:
                p["fallback"] = list(fallback)
            _write_raw(data, registry_path)
            return _project_from_raw(p)
    return None


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
