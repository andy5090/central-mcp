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


def _sanitize_language(value: str | None) -> str | None:
    """Normalize a language preference. Strips whitespace, rejects control chars,
    collapses empty values to None so callers can treat "no preference" uniformly.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"language must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        return None
    if any(c in stripped for c in "\n\r\t\x00"):
        raise ValueError("language must not contain newlines or control characters")
    return stripped


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
    language: str | None = None         # preferred response language; None = agent default (English)

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
            "language": self.language,
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
    raw_language = p.get("language")
    try:
        language = _sanitize_language(raw_language if isinstance(raw_language, str) else None)
    except ValueError:
        language = None
    return Project(
        name=p["name"],
        path=p["path"],
        agent=p.get("agent", "claude"),
        description=p.get("description", ""),
        tags=list(p.get("tags") or []),
        permission_mode=raw_mode,
        fallback=list(raw_fallback) if raw_fallback else None,
        session_id=session_id,
        language=language,
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
    language: str | None = None,
    registry_path: Path | None = None,
) -> Project:
    """Append a project to registry.yaml. Raises ValueError on duplicate."""
    data = _read_raw(registry_path)
    projects = data.get("projects") or []

    if any((p.get("name") == name) for p in projects):
        raise ValueError(f"project {name!r} already exists")

    lang = _sanitize_language(language)

    entry: dict[str, Any] = {
        "name": name,
        "path": path_,
        "agent": agent,
        "description": description,
        "tags": list(tags or []),
    }
    if lang is not None:
        entry["language"] = lang
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
    language: str | None = None,
    registry_path: Path | None = None,
) -> Project | None:
    """Update fields of an existing project. Omitted args stay unchanged.

    `session_id=""` (empty string) clears the pin, returning the project
    to the agent's default resume-latest behavior. `language=""` clears
    the preferred-language pin, reverting dispatches to the agent's
    default (English). Any non-empty string is stored verbatim.

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
            if language is not None:
                lang = _sanitize_language(language)
                if lang is None:
                    p.pop("language", None)
                else:
                    p["language"] = lang
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


# ---------- workspaces ----------

def _migrate_workspaces(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Ensure registry data has a `workspaces` map.

    Returns (data, was_modified). Callers that pass a non-empty data dict
    and get was_modified=True should persist the result.

    When `workspaces` is absent (pre-workspace registry), `default` is
    seeded with all existing project names so the YAML reflects reality.
    New projects added later start as orphans until assigned somewhere.

    Note: the active workspace name (`current_workspace`) lives in
    `config.toml`, not here. If a legacy registry still carries that key,
    `config.ensure_initialized()` migrates it out on startup.
    """
    modified = False
    if "workspaces" not in data:
        existing = [p["name"] for p in (data.get("projects") or []) if p.get("name")]
        data["workspaces"] = {"default": existing}
        modified = True
    return data, modified


def load_workspaces(path: Path | None = None) -> dict[str, list[str]]:
    """Return the workspaces map, auto-migrating if needed.

    Returns empty dict when no registry file exists yet (fresh install
    before `init` is run).
    """
    data = _read_raw(path)
    if not data:
        return {}
    data, modified = _migrate_workspaces(data)
    if modified:
        _write_raw(data, path)
    return {k: list(v) for k, v in (data.get("workspaces") or {}).items()}


def add_workspace(name: str, path: Path | None = None) -> None:
    """Add a new empty workspace. Raises ValueError if already exists."""
    data = _read_raw(path)
    data, _ = _migrate_workspaces(data)
    workspaces = data.get("workspaces") or {}
    if name in workspaces:
        raise ValueError(f"workspace {name!r} already exists")
    workspaces[name] = []
    data["workspaces"] = workspaces
    _write_raw(data, path)


def add_to_workspace(project_name: str, workspace_name: str, path: Path | None = None) -> None:
    """Add a project to a workspace membership list.

    Raises ValueError if the project or workspace doesn't exist.
    Idempotent — adding an already-listed project is a no-op.

    When adding to a non-default workspace, the project is also removed from
    `default` so each project appears in exactly one workspace in the YAML.
    """
    data = _read_raw(path)
    data, _ = _migrate_workspaces(data)
    known_projects = {p["name"] for p in (data.get("projects") or []) if p.get("name")}
    if project_name not in known_projects:
        raise ValueError(f"unknown project {project_name!r}")
    workspaces = data.get("workspaces") or {}
    if workspace_name not in workspaces:
        raise ValueError(f"unknown workspace {workspace_name!r}")
    if project_name not in workspaces[workspace_name]:
        workspaces[workspace_name].append(project_name)
    # Moving to a named workspace: remove from default so the YAML doesn't
    # show stale default membership after the project has been assigned.
    if workspace_name != "default" and project_name in workspaces.get("default", []):
        workspaces["default"] = [m for m in workspaces["default"] if m != project_name]
    data["workspaces"] = workspaces
    _write_raw(data, path)


def remove_from_workspace(project_name: str, workspace_name: str, path: Path | None = None) -> bool:
    """Remove a project from a workspace. Returns False if not a member."""
    data = _read_raw(path)
    data, _ = _migrate_workspaces(data)
    workspaces = data.get("workspaces") or {}
    members = list(workspaces.get(workspace_name, []))
    if project_name not in members:
        return False
    members.remove(project_name)
    workspaces[workspace_name] = members
    data["workspaces"] = workspaces
    _write_raw(data, path)
    return True


def projects_in_workspace(workspace_name: str, path: Path | None = None) -> list[Project]:
    """Return projects belonging to a workspace.

    For 'default': includes projects explicitly listed in 'default' plus
    any orphans (projects not listed in any other workspace).
    For named workspaces: only explicitly listed members.
    """
    data = _read_raw(path)
    if not data:
        return []
    data, modified = _migrate_workspaces(data)
    if modified:
        _write_raw(data, path)

    all_projects = [_project_from_raw(p) for p in (data.get("projects") or [])]
    workspaces = data.get("workspaces") or {}

    if workspace_name == "default":
        in_other_workspace: set[str] = set()
        for ws_name, members in workspaces.items():
            if ws_name != "default":
                in_other_workspace.update(members)
        default_explicit = set(workspaces.get("default", []))
        return [p for p in all_projects
                if p.name in default_explicit or p.name not in in_other_workspace]

    members = set(workspaces.get(workspace_name, []))
    return [p for p in all_projects if p.name in members]
