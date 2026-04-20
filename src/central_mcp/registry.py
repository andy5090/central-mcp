from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from central_mcp import paths
from central_mcp.adapters.base import VALID_PERMISSION_MODES


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
    permission_mode: str | None = None  # None = not yet decided; defaults to "bypass" at dispatch time
    fallback: list[str] | None = None   # agents to try if primary fails
    session_id: str | None = None       # optional pin; empty/None = use agent's resume-latest

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "agent": self.agent,
            "description": self.description,
            "tags": self.tags or [],
            "permission_mode": self.permission_mode,
            "fallback": self.fallback or [],
            "session_id": self.session_id,
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
    raw_mode = p.get("permission_mode")
    if raw_mode is not None and raw_mode not in VALID_PERMISSION_MODES:
        raw_mode = None
    raw_fallback = p.get("fallback")
    raw_session = p.get("session_id")
    session_id = raw_session if isinstance(raw_session, str) and raw_session else None
    return Project(
        name=p["name"],
        path=p["path"],
        agent=p.get("agent", "claude"),
        description=p.get("description", ""),
        tags=list(p.get("tags") or []),
        permission_mode=raw_mode,
        fallback=list(raw_fallback) if raw_fallback else None,
        session_id=session_id,
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


def update_project(
    name: str,
    *,
    agent: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    permission_mode: str | None = None,
    fallback: list[str] | None = None,
    session_id: str | None = None,
    registry_path: Path | None = None,
) -> Project | None:
    """Update fields of an existing project. Omitted args stay unchanged.

    `session_id=""` (empty string) clears the pin, returning the project
    to the agent's default resume-latest behavior. Any non-empty string
    is stored verbatim.

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
            if permission_mode is not None:
                if permission_mode not in VALID_PERMISSION_MODES:
                    raise ValueError(
                        f"invalid permission_mode {permission_mode!r}; "
                        f"valid: {sorted(VALID_PERMISSION_MODES)}"
                    )
                p["permission_mode"] = permission_mode
                # Drop any legacy field so YAML has exactly one source of truth.
                p.pop("bypass", None)
            if fallback is not None:
                p["fallback"] = list(fallback)
            if session_id is not None:
                if session_id == "":
                    p.pop("session_id", None)
                else:
                    p["session_id"] = session_id
            _write_raw(data, registry_path)
            return _project_from_raw(p)
    return None


def reorder(
    order: list[str],
    *,
    strict: bool = False,
    registry_path: Path | None = None,
) -> list[Project]:
    """Rewrite the registry with `order` applied to the `projects` list.

    `strict=False` (default, lenient): names in `order` move to the
    front in the given sequence; any project not mentioned stays in
    its original position relative to other unmentioned projects, just
    pushed after the explicitly-ordered prefix. Supports partial moves
    without having to spell out every registered project.

    `strict=True`: `order` must exactly match the set of registered
    project names (same length, same members). Raises ValueError if
    missing or extra names are present.

    Raises ValueError for unknown names or duplicates in `order`.
    Returns the projects in their new order.
    """
    data = _read_raw(registry_path)
    projects = data.get("projects") or []

    existing = {p["name"]: p for p in projects if p.get("name")}
    if len(existing) != len(projects):
        # Duplicate names in registry — caller can't cleanly reorder
        # something that isn't uniquely identified.
        raise ValueError("registry contains duplicate project names")

    seen: set[str] = set()
    for name in order:
        if name not in existing:
            raise ValueError(
                f"unknown project {name!r} in reorder list; "
                f"known: {sorted(existing)}"
            )
        if name in seen:
            raise ValueError(f"duplicate project {name!r} in reorder list")
        seen.add(name)

    if strict and seen != set(existing):
        missing = sorted(set(existing) - seen)
        raise ValueError(
            f"strict reorder requires every registered project; "
            f"missing: {missing}"
        )

    reordered = [existing[name] for name in order]
    # Tail: unmentioned projects in their original relative order.
    for p in projects:
        if p.get("name") not in seen:
            reordered.append(p)

    data["projects"] = reordered
    _write_raw(data, registry_path)
    return [_project_from_raw(p) for p in reordered]


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
