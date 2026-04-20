"""Per-agent adapters.

An `Adapter` describes how to talk to a coding-agent CLI in three modes:

- `launch` — the argv to spawn when a human wants an interactive session
  (used by `central-mcp up` to populate each project's tmux pane).
- `exec_argv(prompt, resume=True, permission_mode=..., session_id=None)` —
  a one-shot non-interactive argv that writes the response to stdout and
  exits. This is what the `dispatch` MCP tool invokes for every dispatch.
- `list_sessions(cwd, limit=20)` — enumerate conversation sessions the
  agent has saved for the given working directory, so the orchestrator
  can surface candidates when the user wants to resume a specific
  thread. Returns an empty list if the agent has no session store on
  this machine or the adapter hasn't implemented discovery yet.

Adapters that have no non-interactive mode return `None` from
`exec_argv` — the caller surfaces a clear error instead of silently
doing nothing.

`permission_mode` is one of:
  - `"bypass"`      — append the agent's permission-skip flag.
  - `"auto"`        — claude only: classifier-reviewed auto mode.
                       Other agents fall back to no permission flag.
  - `"restricted"`  — no permission-skip flag.

`session_id` is a **one-shot override** for conversation resumption.
  - `None` and `resume=True` → use the agent's "resume latest" flag
    (claude `--continue`, codex `resume --last`, etc). droid has no
    headless "resume latest" so it stays fresh.
  - `None` and `resume=False` → fresh session, no resume flag.
  - A string → the adapter's specific-session flag (claude `-r <id>`,
    codex `resume <id>`, opencode `-s <id>`, droid `-s <id>`,
    gemini `--resume <index>`). After this dispatch the agent's own
    "resume latest" mechanism picks the just-used session up naturally,
    so one-shot switches don't need to be re-stated every dispatch.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


VALID_PERMISSION_MODES = frozenset({"bypass", "auto", "restricted"})


@dataclass
class SessionInfo:
    """Minimal description of a resumable conversation session.

    All fields but `id` are optional — adapters fill in whatever they
    can cheaply surface and leave the rest as None.
    """
    id: str
    title: str | None = None
    created: str | None = None   # ISO 8601, when known
    modified: str | None = None  # ISO 8601, when known (mtime fallback)
    turns: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "created": self.created,
            "modified": self.modified,
            "turns": self.turns,
        }


@dataclass
class Adapter:
    name: str
    launch: Sequence[str] = ()
    has_exec: bool = False
    supports_auto: bool = False

    def launch_command(self) -> str:
        """Shell-joined interactive launch command for tmux panes."""
        return " ".join(self.launch)

    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
        session_id: str | None = None,
    ) -> list[str] | None:
        return None

    def list_sessions(
        self,
        cwd: str | Path,
        limit: int = 20,
    ) -> list[SessionInfo]:
        """Enumerate resumable sessions for this agent in `cwd`.

        Default: no sessions known. Override in subclasses that can
        discover them (via filesystem scan or subprocess).
        """
        return []


# ---------- shared helpers ----------

def _slug_cwd(cwd: str | Path) -> str:
    """Match claude/droid's on-disk per-project directory naming.

    Both agents encode the cwd by replacing every `/` with `-` and
    leave everything else intact, e.g.:
        /Users/andy/X  ->  -Users-andy-X
    """
    return str(Path(cwd).resolve()).replace("/", "-")


def _mtime_iso(path: Path) -> str | None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _list_jsonl_directory(dir_path: Path, limit: int) -> list[SessionInfo]:
    """Scan `<dir>/<uuid>.jsonl` files, newest first.

    Shared by claude (`~/.claude/projects/<slug>/`) and droid
    (`~/.factory/sessions/<slug>/`). The session id is the filename
    stem; the title (when present) is pulled best-effort from the first
    JSON line's common metadata fields.
    """
    if not dir_path.is_dir():
        return []

    entries: list[tuple[float, Path]] = []
    for p in dir_path.glob("*.jsonl"):
        try:
            entries.append((p.stat().st_mtime, p))
        except OSError:
            continue
    entries.sort(reverse=True)

    results: list[SessionInfo] = []
    for mtime, path in entries[:limit]:
        title: str | None = None
        try:
            with path.open() as fh:
                first_line = fh.readline().strip()
        except OSError:
            first_line = ""
        if first_line:
            try:
                record = json.loads(first_line)
            except json.JSONDecodeError:
                record = {}
            title = _extract_title(record)
        results.append(SessionInfo(
            id=path.stem,
            title=title,
            modified=datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
        ))
    return results


def _extract_title(record: dict) -> str | None:
    """Best-effort title extraction from a session record dict.

    Different agents use different keys; try the common ones and fall
    back to the first user-message text (trimmed) if nothing else fits.
    """
    for key in ("title", "summary", "name"):
        val = record.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:120]
    # Nested claude-ish / codex-ish shapes
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else None
    if payload:
        for key in ("title", "summary", "name"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:120]
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else None
    if meta:
        for key in ("title", "summary", "name"):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:120]
    # First user message text (works for claude/codex first-line formats)
    msg = record.get("message") or payload or {}
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text") or first.get("content")
                if isinstance(text, str) and text.strip():
                    return text.strip().split("\n", 1)[0][:120]
        elif isinstance(content, str) and content.strip():
            return content.strip().split("\n", 1)[0][:120]
    return None


# ---------- per-agent adapters ----------

class _Claude(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
        session_id: str | None = None,
    ) -> list[str] | None:
        argv = ["claude", "-p", prompt]
        if session_id:
            argv += ["-r", session_id]
        elif resume:
            argv.append("--continue")
        if permission_mode == "bypass":
            argv.append("--dangerously-skip-permissions")
        elif permission_mode == "auto":
            argv.extend(["--enable-auto-mode", "--permission-mode", "auto"])
        return argv

    def list_sessions(self, cwd: str | Path, limit: int = 20) -> list[SessionInfo]:
        project_dir = Path.home() / ".claude" / "projects" / _slug_cwd(cwd)
        return _list_jsonl_directory(project_dir, limit)


class _Codex(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
        session_id: str | None = None,
    ) -> list[str] | None:
        if session_id:
            argv = ["codex", "exec", "resume", session_id, prompt]
        elif resume:
            argv = ["codex", "exec", "resume", "--last", prompt]
        else:
            argv = ["codex", "exec", prompt]
        if permission_mode == "bypass":
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        return argv

    def list_sessions(self, cwd: str | Path, limit: int = 20) -> list[SessionInfo]:
        """Filter `~/.codex/sessions/**/*.jsonl` by session_meta's cwd.

        Codex stores one rollout-<ts>-<uuid>.jsonl per session under a
        date-partitioned tree; the first JSONL line carries the session
        id and cwd. We scan recent files (bounded to 200 candidates) and
        pick those whose cwd matches the target until we have `limit`.
        """
        base = Path.home() / ".codex" / "sessions"
        if not base.is_dir():
            return []
        candidates: list[tuple[float, Path]] = []
        for p in base.rglob("*.jsonl"):
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                continue
        candidates.sort(reverse=True)

        target_cwd = str(Path(cwd).resolve())
        results: list[SessionInfo] = []
        for mtime, path in candidates[:200]:
            if len(results) >= limit:
                break
            try:
                with path.open() as fh:
                    first_line = fh.readline().strip()
                    second_line = fh.readline().strip()
            except OSError:
                continue
            if not first_line:
                continue
            try:
                meta = json.loads(first_line)
            except json.JSONDecodeError:
                continue
            payload = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
            sess_cwd = payload.get("cwd")
            if not sess_cwd:
                continue
            try:
                if str(Path(sess_cwd).resolve()) != target_cwd:
                    continue
            except OSError:
                continue
            sid = payload.get("id") or path.stem
            created = payload.get("timestamp")
            # Title from the first user message (second line, best-effort).
            title = None
            if second_line:
                try:
                    rec2 = json.loads(second_line)
                except json.JSONDecodeError:
                    rec2 = {}
                title = _extract_title(rec2)
            results.append(SessionInfo(
                id=sid,
                title=title,
                created=created if isinstance(created, str) else None,
                modified=datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
            ))
        return results


class _Gemini(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
        session_id: str | None = None,
    ) -> list[str] | None:
        argv = ["gemini", "-p", prompt]
        if session_id:
            argv += ["--resume", session_id]
        elif resume:
            argv += ["--resume", "latest"]
        if permission_mode == "bypass":
            argv.append("--yolo")
        return argv

    def list_sessions(self, cwd: str | Path, limit: int = 20) -> list[SessionInfo]:
        """Parse `gemini --list-sessions` output run from `cwd`.

        Format is not formally documented and may evolve; the parser is
        tolerant — numeric-indexed lines are kept, anything else is
        dropped. Exit code != 0 (including the "no sessions found"
        message) yields an empty list.
        """
        if shutil.which("gemini") is None:
            return []
        try:
            result = subprocess.run(
                ["gemini", "--list-sessions"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if result.returncode != 0:
            return []
        sessions: list[SessionInfo] = []
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if not parts or not parts[0].isdigit():
                continue
            sid = parts[0]
            title = parts[1].strip() if len(parts) > 1 else None
            sessions.append(SessionInfo(id=sid, title=title))
            if len(sessions) >= limit:
                break
        return sessions


class _Droid(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
        session_id: str | None = None,
    ) -> list[str] | None:
        # `droid exec` has no "resume latest" — always fresh unless an
        # explicit session_id is provided. `resume=True` without a
        # session_id is therefore a no-op, matching the current
        # behavior.
        argv = ["droid", "exec", prompt]
        if session_id:
            argv += ["-s", session_id]
        if permission_mode == "bypass":
            argv.append("--skip-permissions-unsafe")
        return argv

    def list_sessions(self, cwd: str | Path, limit: int = 20) -> list[SessionInfo]:
        project_dir = Path.home() / ".factory" / "sessions" / _slug_cwd(cwd)
        return _list_jsonl_directory(project_dir, limit)


class _OpenCode(Adapter):
    def exec_argv(
        self,
        prompt: str,
        *,
        resume: bool = True,
        permission_mode: str = "restricted",
        session_id: str | None = None,
    ) -> list[str] | None:
        argv = ["opencode", "run", prompt]
        if session_id:
            argv += ["-s", session_id]
        elif resume:
            argv.append("--continue")
        if permission_mode == "bypass":
            argv.append("--dangerously-skip-permissions")
        return argv

    def list_sessions(self, cwd: str | Path, limit: int = 20) -> list[SessionInfo]:
        """Parse `opencode session list`. NOT cwd-scoped — opencode's
        session list is global. The orchestrator still gets a useful
        candidate set for pin selection; cwd filtering is not possible
        via this path.
        """
        if shutil.which("opencode") is None:
            return []
        try:
            result = subprocess.run(
                ["opencode", "session", "list"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if result.returncode != 0:
            return []
        sessions: list[SessionInfo] = []
        for raw in result.stdout.splitlines():
            line = raw.rstrip()
            if not line or line.lstrip().startswith(("Session ID", "─", "-")):
                continue
            # Session IDs are prefixed `ses_`. Everything after the id
            # up to the last time/date column is the title.
            parts = line.split()
            if not parts or not parts[0].startswith("ses_"):
                continue
            sid = parts[0]
            # Trailing columns carry the date; keep the middle bit as
            # title, best-effort.
            rest = line[len(sid):].strip()
            title: str | None = None
            if rest:
                # Strip the trailing "H:MM AM/PM · M/D/YYYY" style tail.
                tail_markers = (" · ", "·")
                tail_idx = -1
                for marker in tail_markers:
                    i = rest.rfind(marker)
                    if i > tail_idx:
                        tail_idx = i
                if tail_idx > 0:
                    # Cut off the date column group (rough heuristic).
                    tokens = rest[:tail_idx].rsplit(None, 1)
                    title = tokens[0].strip() if tokens else None
                else:
                    title = rest
            sessions.append(SessionInfo(id=sid, title=title[:120] if title else None))
            if len(sessions) >= limit:
                break
        return sessions


# `amp` was previously supported as a dispatch target but has been
# removed: Amp Free rejects `amp -x` with "Execute mode ... require
# paid credits", making the adapter unusable for the majority of
# potential users.


_ADAPTERS: dict[str, Adapter] = {
    "claude":   _Claude("claude",   launch=("claude",),   has_exec=True, supports_auto=True),
    "codex":    _Codex("codex",     launch=("codex",),    has_exec=True),
    "gemini":   _Gemini("gemini",   launch=("gemini",),   has_exec=True),
    "droid":    _Droid("droid",     launch=("droid",),    has_exec=True),
    "opencode": _OpenCode("opencode", launch=("opencode",), has_exec=True),
}

_FALLBACK_ADAPTER = Adapter("(unknown)", launch=(), has_exec=False)

VALID_AGENTS = {"claude", "codex", "gemini", "droid", "opencode"}


def get_adapter(name: str) -> Adapter:
    return _ADAPTERS.get(name, _FALLBACK_ADAPTER)
