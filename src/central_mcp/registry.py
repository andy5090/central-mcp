from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_REGISTRY_PATH = Path(
    os.environ.get("CENTRAL_MCP_REGISTRY")
    or Path(__file__).resolve().parents[2] / "registry.yaml"
)


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


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> list[Project]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    projects_raw = data.get("projects") or []
    projects: list[Project] = []
    for p in projects_raw:
        tmux_raw = p.get("tmux") or {}
        projects.append(
            Project(
                name=p["name"],
                path=p["path"],
                agent=p.get("agent", "shell"),
                tmux=TmuxTarget(
                    session=tmux_raw.get("session", "central"),
                    window=tmux_raw.get("window", "projects"),
                    pane=int(tmux_raw.get("pane", 0)),
                ),
                description=p.get("description", ""),
                tags=p.get("tags") or [],
            )
        )
    return projects


def find_project(name: str, path: Path = DEFAULT_REGISTRY_PATH) -> Project | None:
    for p in load_registry(path):
        if p.name == name:
            return p
    return None
