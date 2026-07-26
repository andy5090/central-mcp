"""Project pulse — stateless, on-demand aggregation of a project's real state.

The data spine of the Portfolio PM track (see docs/ROADMAP.md). Answers
"what happened here, where does it stand, what's next?" for one project
by reading the signals that already exist rather than by keeping a
record of its own:

  - **git** — branch, upstream ahead/behind, working-tree dirt, recent
    commits. This is the signal that closes central-mcp's oldest blind
    spot: work done *without* going through dispatch (direct commits,
    interactive agent sessions, manual edits) is invisible to the
    timeline but plainly visible to git.
  - **dispatches** — in-flight work from the shared SQLite state, plus
    recent outcomes and per-outcome counts from the project's jsonl log.
  - **sessions** — resumable agent conversations, for the agents whose
    adapters can enumerate them.
  - **pull requests** — open PRs via `gh`, when it's installed and the
    repo has a GitHub remote (opt-in; it is the only network call here).

Every signal degrades independently: a missing git binary, an
unreadable log, or an unauthenticated `gh` downgrades that one section
to `available: false` with a reason and never fails the pulse. Nothing
in this module writes state — call it as often as you like.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from central_mcp import dispatches_db, events
from central_mcp.adapters import get_adapter
from central_mcp.adapters.base import Adapter
from central_mcp.registry import Project, find_project

_GIT_TIMEOUT = 5.0
_GH_TIMEOUT = 8.0
_MAX_DIRTY_FILES = 12
_MAX_PRS = 10

# A dispatch row still marked `running` after this long is almost
# certainly abandoned: the default dispatch timeout is 600s, and only
# the originating process can write the terminal row, so a crashed or
# restarted server leaves the row `running` forever. Generous enough to
# clear long custom timeouts, tight enough that a PM briefing never
# reports a dead process as live work.
_STALE_AFTER_SEC = 2 * 3600

# Unit separator between fields of one `git log` record. Chosen over a
# printable delimiter because commit subjects routinely contain `|`,
# `:` and friends; %s never contains a newline, so records stay
# one-per-line and \x1f is enough on its own.
_LOG_FORMAT = "%H%x1f%h%x1f%an%x1f%cI%x1f%s"


# ---------- small helpers ----------

def _run(argv: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str] | None:
    """Run a command, returning None instead of raising on any failure."""
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,     # callers inspect returncode to build a `reason`
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _age_sec(value: str | None, *, now: datetime | None = None) -> float | None:
    dt = _parse_iso(value)
    if dt is None:
        return None
    return max(0.0, ((now or _now()) - dt).total_seconds())


def humanize_age(seconds: float | None) -> str:
    """Render an age in seconds as a compact `2h ago` style string."""
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 90:
        return f"{round(minutes)}m ago"
    hours = minutes / 60
    if hours < 36:
        return f"{round(hours)}h ago"
    days = hours / 24
    if days < 14:
        return f"{days:.1f}d ago".replace(".0d", "d")
    return f"{round(days)}d ago"


def humanize_duration(seconds: float | None) -> str:
    """Render an elapsed span as `4m` / `1.5h` / `92d` (no `ago` suffix)."""
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = seconds / 60
    if minutes < 90:
        return f"{round(minutes)}m"
    hours = minutes / 60
    if hours < 36:
        return f"{hours:.1f}h".replace(".0h", "h")
    return f"{round(hours / 24)}d"


def _oneline(text: str | None, limit: int = 90) -> str:
    """Collapse a prompt / message to a single truncated display line.

    Dispatch prompts are routinely multi-paragraph; pasted verbatim they
    shred any list-based rendering.
    """
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _latest(*iso_values: str | None) -> str | None:
    """Return the most recent of several ISO timestamps, normalized to UTC.

    Sources disagree on offset — git's `%cI` is the committer's local
    time, dispatch logs are UTC — so the winner is re-rendered in UTC.
    Without that, callers comparing two projects' `last_activity_at`
    lexicographically (the obvious thing to do with ISO strings) would
    order them by wall-clock digits rather than by instant.
    """
    best: datetime | None = None
    for value in iso_values:
        dt = _parse_iso(value)
        if dt is None:
            continue
        if best is None or dt > best:
            best = dt
    if best is None:
        return None
    return best.astimezone(timezone.utc).isoformat(timespec="milliseconds")


# ---------- git ----------

def _porcelain_path(line: str) -> tuple[str, str] | None:
    """Extract (kind, path) from one `git status --porcelain=v2` entry.

    `kind` is one of `staged` / `unstaged` / `both` / `untracked` /
    `conflicted`. Returns None for header and ignored lines.
    """
    if line.startswith("? "):
        return "untracked", line[2:]
    if line.startswith("1 "):
        fields = line.split(" ", 8)
        if len(fields) < 9:
            return None
        xy, path = fields[1], fields[8]
    elif line.startswith("2 "):
        # Rename/copy: trailing field is `<path>\t<origPath>`.
        fields = line.split(" ", 9)
        if len(fields) < 10:
            return None
        xy, path = fields[1], fields[9].split("\t", 1)[0]
    elif line.startswith("u "):
        fields = line.split(" ", 10)
        if len(fields) < 11:
            return None
        return "conflicted", fields[10]
    else:
        return None

    staged = xy[0] != "."
    unstaged = len(xy) > 1 and xy[1] != "."
    if staged and unstaged:
        kind = "both"
    elif staged:
        kind = "staged"
    else:
        kind = "unstaged"
    return kind, path


def git_snapshot(
    path: str | Path,
    *,
    commits: int = 5,
    max_files: int = _MAX_DIRTY_FILES,
) -> dict[str, Any]:
    """Branch, upstream divergence, working-tree dirt, and recent commits.

    Two subprocess calls: one `git status --porcelain=v2 --branch` (which
    carries branch, upstream and per-file state together) and one
    `git log`. Both are local and cheap.
    """
    snap: dict[str, Any] = {
        "available": False,
        "reason": None,
        "branch": None,
        "detached": False,
        "upstream": None,
        "ahead": None,
        "behind": None,
        "dirty": {
            "staged": 0,
            "unstaged": 0,
            "untracked": 0,
            "conflicted": 0,
            "total": 0,
            "files": [],
            "truncated": False,
        },
        "head": None,
        "recent_commits": [],
    }

    repo = Path(path).expanduser()
    if not repo.is_dir():
        snap["reason"] = "project path does not exist"
        return snap
    if shutil.which("git") is None:
        snap["reason"] = "git not installed"
        return snap

    status = _run(["git", "status", "--porcelain=v2", "--branch"], repo, _GIT_TIMEOUT)
    if status is None:
        snap["reason"] = "git status failed to run"
        return snap
    if status.returncode != 0:
        stderr = (status.stderr or "").strip().splitlines()
        snap["reason"] = stderr[0] if stderr else "not a git repository"
        return snap

    snap["available"] = True
    dirty = snap["dirty"]
    files: list[str] = []
    for line in (status.stdout or "").splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head "):].strip()
            if head == "(detached)":
                snap["detached"] = True
            else:
                snap["branch"] = head
            continue
        if line.startswith("# branch.upstream "):
            snap["upstream"] = line[len("# branch.upstream "):].strip()
            continue
        if line.startswith("# branch.ab "):
            parts = line[len("# branch.ab "):].split()
            for part in parts:
                try:
                    if part.startswith("+"):
                        snap["ahead"] = int(part[1:])
                    elif part.startswith("-"):
                        snap["behind"] = int(part[1:])
                except ValueError:
                    pass
            continue
        if line.startswith("#"):
            continue
        parsed = _porcelain_path(line)
        if parsed is None:
            continue
        kind, file_path = parsed
        if kind == "both":
            dirty["staged"] += 1
            dirty["unstaged"] += 1
        else:
            dirty[kind] += 1
        dirty["total"] += 1
        if len(files) < max_files:
            marker = {
                "staged": "S", "unstaged": "M", "both": "SM",
                "untracked": "?", "conflicted": "!",
            }[kind]
            files.append(f"{marker} {file_path}")
    dirty["files"] = files
    dirty["truncated"] = dirty["total"] > len(files)

    if commits > 0:
        log = _run(
            ["git", "log", f"-{int(commits)}", f"--format={_LOG_FORMAT}"],
            repo,
            _GIT_TIMEOUT,
        )
        if log is not None and log.returncode == 0:
            now = _now()
            for line in (log.stdout or "").splitlines():
                fields = line.split("\x1f")
                if len(fields) < 5:
                    continue
                sha, short, author, committed_at, subject = fields[:5]
                snap["recent_commits"].append({
                    "sha": sha,
                    "short_sha": short,
                    "author": author,
                    "committed_at": committed_at,
                    "age_sec": _age_sec(committed_at, now=now),
                    "subject": subject,
                })
    if snap["recent_commits"]:
        snap["head"] = snap["recent_commits"][0]
    return snap


# ---------- dispatches ----------

def dispatch_snapshot(project_name: str, *, history: int = 5) -> dict[str, Any]:
    """In-flight dispatches plus recent outcomes for one project.

    In-flight comes from the shared SQLite state (authoritative across
    processes); recent outcomes come from the project's append-only
    jsonl log, which survives db pruning and carries prompts.
    """
    snap: dict[str, Any] = {
        "in_flight": [],
        "stale": [],
        "recent": [],
        "counts": {"succeeded": 0, "failed": 0, "cancelled": 0, "total": 0},
        "last_activity_at": None,
    }

    try:
        now_ts = _now().timestamp()
        for e in dispatches_db.list_active():
            if e.get("project") != project_name:
                continue
            started = e.get("started") or 0
            elapsed = max(0.0, now_ts - started)
            entry = {
                "dispatch_id": e.get("id"),
                "agent": e.get("agent"),
                "prompt": (e.get("prompt") or "")[:200],
                "started_at": datetime.fromtimestamp(
                    started, tz=timezone.utc
                ).isoformat(timespec="seconds"),
                "elapsed_sec": elapsed,
                "stale": elapsed > _STALE_AFTER_SEC,
            }
            # Stale rows are reported separately rather than dropped: a
            # never-finalized dispatch is itself a fact worth briefing on,
            # but counting it as live work would be a false report.
            snap["stale" if entry["stale"] else "in_flight"].append(entry)
    except Exception:
        pass

    records = events.read_jsonl(events.log_path(project_name))
    starts: dict[str, dict[str, Any]] = {}
    # Keep each terminal's line position: `ts` has millisecond precision,
    # so dispatches finishing inside the same millisecond tie. The log is
    # append-only, which makes file order the authoritative tiebreaker.
    terminals: list[tuple[str, int, dict[str, Any]]] = []
    for idx, r in enumerate(records):
        evt = r.get("event")
        if evt == "start":
            starts[r.get("id", "")] = r
        elif evt in ("complete", "error", "cancelled"):
            terminals.append((r.get("ts") or "", idx, r))

    counts = snap["counts"]
    for _, _, t in terminals:
        counts["total"] += 1
        evt = t.get("event")
        if evt == "cancelled":
            counts["cancelled"] += 1
        elif evt == "complete" and t.get("ok"):
            counts["succeeded"] += 1
        else:
            counts["failed"] += 1

    terminals.sort(key=lambda item: (item[0], item[1]), reverse=True)
    now = _now()
    for _, _, t in terminals[:history]:
        s = starts.get(t.get("id", ""), {})
        ts = t.get("ts")
        snap["recent"].append({
            "dispatch_id": t.get("id"),
            "event": t.get("event"),
            "ts": ts,
            "age_sec": _age_sec(ts, now=now),
            "ok": bool(t.get("ok")),
            "agent": t.get("agent_used") or s.get("agent"),
            "duration_sec": t.get("duration_sec"),
            "prompt": (s.get("prompt") or "")[:200],
            "output_preview": t.get("output_preview", ""),
            "error": t.get("error"),
            "tokens": events.token_total(t.get("tokens")),
        })
    if terminals:
        snap["last_activity_at"] = terminals[0][2].get("ts")
    return snap


# ---------- agent sessions ----------

def session_snapshot(project: Project, *, limit: int = 3) -> dict[str, Any]:
    """Resumable agent conversations, for adapters that can enumerate them."""
    snap: dict[str, Any] = {
        "available": False,
        "reason": None,
        "count": 0,
        "latest": None,
        "sessions": [],
    }
    try:
        adapter = get_adapter(project.agent)
    except Exception as exc:
        snap["reason"] = f"no adapter for {project.agent!r}: {exc}"
        return snap
    # Distinguish "this agent has no session reader" from "no sessions
    # found" — the base implementation returns [] for both otherwise.
    if type(adapter).list_sessions is Adapter.list_sessions:
        snap["reason"] = f"{project.agent} has no session reader"
        return snap
    try:
        sessions = adapter.list_sessions(project.path, limit=limit)
    except Exception as exc:
        snap["reason"] = f"list_sessions failed: {exc}"
        return snap
    snap["available"] = True
    snap["count"] = len(sessions)
    snap["sessions"] = [s.to_dict() for s in sessions]
    if sessions:
        snap["latest"] = sessions[0].to_dict()
    return snap


# ---------- pull requests ----------

def pr_snapshot(path: str | Path, *, limit: int = _MAX_PRS) -> dict[str, Any]:
    """Open pull requests via `gh`. The only network call in a pulse."""
    snap: dict[str, Any] = {
        "available": False,
        "reason": None,
        "count": 0,
        "open": [],
    }
    repo = Path(path).expanduser()
    if not repo.is_dir():
        snap["reason"] = "project path does not exist"
        return snap
    if shutil.which("gh") is None:
        snap["reason"] = "gh not installed"
        return snap
    proc = _run(
        [
            "gh", "pr", "list", "--state", "open", "--limit", str(int(limit)),
            "--json", "number,title,updatedAt,isDraft,headRefName,url",
        ],
        repo,
        _GH_TIMEOUT,
    )
    if proc is None:
        snap["reason"] = "gh timed out"
        return snap
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        snap["reason"] = stderr[0] if stderr else "gh pr list failed"
        return snap
    try:
        rows = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        snap["reason"] = "gh returned unparseable JSON"
        return snap
    now = _now()
    snap["available"] = True
    snap["open"] = [
        {
            "number": r.get("number"),
            "title": r.get("title"),
            "branch": r.get("headRefName"),
            "draft": bool(r.get("isDraft")),
            "updated_at": r.get("updatedAt"),
            "age_sec": _age_sec(r.get("updatedAt"), now=now),
            "url": r.get("url"),
        }
        for r in rows
        if isinstance(r, dict)
    ]
    snap["count"] = len(snap["open"])
    return snap


# ---------- the pulse ----------

def pulse(
    name: str,
    *,
    commits: int = 5,
    history: int = 5,
    include_pr: bool = True,
) -> dict[str, Any]:
    """Aggregate every available signal for one registered project.

    Returns `{"ok": False, "error": ...}` only when the project isn't
    registered — every other failure degrades one section rather than
    the whole pulse.
    """
    project = find_project(name)
    if project is None:
        return {"ok": False, "error": f"unknown project: {name}"}
    return pulse_for(
        project, commits=commits, history=history, include_pr=include_pr
    )


def pulse_for(
    project: Project,
    *,
    commits: int = 5,
    history: int = 5,
    include_pr: bool = True,
) -> dict[str, Any]:
    """`pulse()` for an already-resolved Project (skips the registry read)."""
    git = git_snapshot(project.path, commits=commits)
    dispatches = dispatch_snapshot(project.name, history=history)
    sessions = session_snapshot(project)
    prs = (
        pr_snapshot(project.path)
        if include_pr
        else {"available": False, "reason": "not requested", "count": 0, "open": []}
    )

    head = git.get("head") or {}
    latest_session = sessions.get("latest") or {}
    last_activity_at = _latest(
        head.get("committed_at"),
        dispatches.get("last_activity_at"),
        latest_session.get("modified"),
    )

    return {
        "ok": True,
        "project": project.name,
        "agent": project.agent,
        "path": project.path,
        "description": project.description,
        "generated_at": _now().isoformat(timespec="seconds"),
        "last_activity_at": last_activity_at,
        "last_activity_age_sec": _age_sec(last_activity_at),
        "git": git,
        "dispatches": dispatches,
        "sessions": sessions,
        "pull_requests": prs,
    }


def pulse_many(
    projects: list[Project],
    *,
    commits: int = 3,
    history: int = 3,
    include_pr: bool = False,
    max_workers: int = 8,
) -> list[dict[str, Any]]:
    """Pulse several projects concurrently, preserving input order.

    Defaults are leaner than the single-project ones: a portfolio sweep
    wants breadth, and `include_pr` is off so a 20-project digest doesn't
    fire 20 network calls.
    """
    if not projects:
        return []

    def _one(p: Project) -> dict[str, Any]:
        try:
            return pulse_for(
                p, commits=commits, history=history, include_pr=include_pr
            )
        except Exception as exc:  # a single bad project must not sink the sweep
            return {"ok": False, "project": p.name, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(projects)))) as pool:
        return list(pool.map(_one, projects))


# ---------- rendering ----------

def _git_line(git: dict[str, Any]) -> str:
    if not git.get("available"):
        return f"- **Git** — unavailable ({git.get('reason') or 'unknown'})"
    bits: list[str] = []
    branch = "(detached HEAD)" if git.get("detached") else (git.get("branch") or "?")
    bits.append(f"`{branch}`")
    ahead, behind = git.get("ahead"), git.get("behind")
    if ahead or behind:
        bits.append(f"↑{ahead or 0} ↓{behind or 0}")
    elif git.get("upstream") is None:
        bits.append("no upstream")
    dirty = git.get("dirty") or {}
    if dirty.get("total"):
        parts = [
            f"{dirty[key]} {label}"
            for key, label in (
                ("staged", "staged"),
                ("unstaged", "modified"),
                ("untracked", "untracked"),
                ("conflicted", "conflicted"),
            )
            if dirty.get(key)
        ]
        bits.append(", ".join(parts))
    else:
        bits.append("clean")
    return "- **Git** — " + " · ".join(bits)


def render(p: dict[str, Any]) -> str:
    """Render one pulse as a compact markdown block."""
    if not p.get("ok"):
        return f"### {p.get('project', '?')}\n\n_error: {p.get('error')}_"

    lines = [f"### {p['project']} · `{p['agent']}`"]
    header = f"`{p['path']}` · last activity {humanize_age(p.get('last_activity_age_sec'))}"
    lines += [header, ""]

    git = p.get("git") or {}
    lines.append(_git_line(git))
    for c in (git.get("recent_commits") or [])[:5]:
        lines.append(
            f"    - `{c['short_sha']}` {_oneline(c.get('subject'), 70)} "
            f"({c['author']}, {humanize_age(c.get('age_sec'))})"
        )
    for f in (git.get("dirty") or {}).get("files", [])[:5]:
        lines.append(f"    - {f}")

    d = p.get("dispatches") or {}
    counts = d.get("counts") or {}
    stale = d.get("stale") or []
    summary_bits = [f"{len(d.get('in_flight') or [])} in flight"]
    if stale:
        summary_bits.append(f"{len(stale)} stale")
    summary_bits.append(
        f"{counts.get('succeeded', 0)} ok / {counts.get('failed', 0)} failed"
        f" of {counts.get('total', 0)} total"
    )
    lines.append("- **Dispatches** — " + " · ".join(summary_bits))
    for e in (d.get("in_flight") or [])[:3]:
        lines.append(
            f"    - ⏳ `{e.get('agent') or '?'}` running {humanize_duration(e.get('elapsed_sec'))}"
            f" — {_oneline(e.get('prompt'))}"
        )
    for e in stale[:3]:
        lines.append(
            f"    - ⚠️ `{e.get('agent') or '?'}` never finalized, started "
            f"{humanize_duration(e.get('elapsed_sec'))} ago — {_oneline(e.get('prompt'))}"
        )
    for e in (d.get("recent") or [])[:3]:
        mark = "✅" if e.get("ok") else "❌"
        lines.append(
            f"    - {mark} {humanize_age(e.get('age_sec'))} `{e.get('agent') or '?'}`"
            f" — {_oneline(e.get('prompt'))}"
        )

    s = p.get("sessions") or {}
    if s.get("available"):
        latest = s.get("latest") or {}
        tail = ""
        if latest.get("modified"):
            tail = f", latest {humanize_age(_age_sec(latest['modified']))}"
        lines.append(f"- **Sessions** — {s.get('count', 0)} resumable{tail}")

    prs = p.get("pull_requests") or {}
    if prs.get("available"):
        if prs.get("count"):
            lines.append(f"- **Open PRs** — {prs['count']}")
            for pr in prs["open"][:5]:
                draft = " _(draft)_" if pr.get("draft") else ""
                lines.append(f"    - #{pr['number']} {pr['title']}{draft}")
        else:
            lines.append("- **Open PRs** — none")

    return "\n".join(lines)


def render_many(pulses: list[dict[str, Any]], *, title: str = "Portfolio pulse") -> str:
    """Render a portfolio sweep as one markdown document."""
    if not pulses:
        return f"## {title}\n\n_(no projects)_"
    blocks = [f"## {title}", "", f"_{len(pulses)} project(s) · generated {_now().isoformat(timespec='seconds')}_", ""]
    for p in pulses:
        blocks.append(render(p))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"
