"""Portfolio digest — the pre-rendered push report of the Portfolio PM track.

Builds the daily/weekly summary that resident bridges (Hermes cron, or
any chat-connected agent) forward to the user off-terminal, and that
terminal orchestrators can paste on a "summarize everything" ask.

The rendering lives server-side for the same reason
`token_usage.summary_markdown` does: if the calling LLM composes the
digest itself, every day looks different and omissions are invisible.
A fixed format, computed from `pulse` data, means the same report
shape regardless of which agent delivers it — callers forward
`digest_markdown` verbatim.

Like the pulse it stands on, a digest stores nothing and recomputes
from source on every call. The delivery schedule and any alert
watermarks belong to the *caller* (see the failure-watch recipe in
`data/agentos-skill.md`) — central-mcp stays stateless between requests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from central_mcp import pulse as pulse_mod
from central_mcp.registry import Project

# Show at most this many commits-in-window per active project; the git
# section of a pulse is capped anyway, so past the cap we say "N+".
_COMMIT_SAMPLE = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build(
    projects: list[Project],
    *,
    workspace_label: str = "default",
    since_hours: int = 24,
    quiet_days: int = 7,
    quota: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the portfolio into active / quiet / warnings for one window.

    `quota` is the (already-fetched) normalized quota snapshot, or None
    to omit the quota line — fetching is the caller's choice because it
    can involve subprocess/network work the digest itself shouldn't force.
    """
    window_sec = max(1, since_hours) * 3600
    pulses = pulse_mod.pulse_many(
        projects, commits=_COMMIT_SAMPLE, history=8, include_pr=False
    )

    active: list[dict[str, Any]] = []
    quiet: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for p in pulses:
        name = p.get("project", "?")
        if not p.get("ok"):
            warnings.append({
                "kind": "pulse_failed",
                "project": name,
                "detail": str(p.get("error")),
            })
            continue

        git = p.get("git") or {}
        dirty_total = ((git.get("dirty") or {}).get("total")) or 0
        dispatches = p.get("dispatches") or {}
        age = p.get("last_activity_age_sec")

        for s in dispatches.get("stale") or []:
            warnings.append({
                "kind": "stale_dispatch",
                "project": name,
                "detail": (
                    f"dispatch never finalized, started "
                    f"{pulse_mod.humanize_duration(s.get('elapsed_sec'))} ago"
                ),
            })

        if age is not None and age <= window_sec:
            commits = [
                c for c in (git.get("recent_commits") or [])
                if c.get("age_sec") is not None and c["age_sec"] <= window_sec
            ]
            commit_count = len(commits)
            commits_capped = commit_count >= _COMMIT_SAMPLE
            recent = [
                r for r in (dispatches.get("recent") or [])
                if r.get("age_sec") is not None and r["age_sec"] <= window_sec
            ]
            ok_n = sum(1 for r in recent if r.get("ok"))
            fail_n = sum(
                1 for r in recent
                if not r.get("ok") and r.get("event") != "cancelled"
            )
            for r in recent:
                if not r.get("ok") and r.get("event") != "cancelled":
                    warnings.append({
                        "kind": "dispatch_failed",
                        "project": name,
                        "detail": (
                            f"dispatch failed "
                            f"{pulse_mod.humanize_age(r.get('age_sec'))}"
                            + (f" — {r['error']}" if r.get("error") else "")
                        ),
                    })
            active.append({
                "project": name,
                "agent": p.get("agent"),
                "branch": (
                    "(detached)" if git.get("detached") else git.get("branch")
                ),
                "commits": commit_count,
                "commits_capped": commits_capped,
                "latest_subject": (
                    commits[0].get("subject") if commits else None
                ),
                "dispatch_ok": ok_n,
                "dispatch_failed": fail_n,
                "in_flight": len(dispatches.get("in_flight") or []),
                "dirty": dirty_total,
                "last_activity_age_sec": age,
            })
        else:
            entry = {
                "project": name,
                "last_activity_age_sec": age,
                "dirty": dirty_total,
            }
            quiet.append(entry)
            if age is not None and age > max(1, quiet_days) * 86400 and dirty_total:
                # The classic dropped ball: a project nobody has touched
                # in a while, with uncommitted work still sitting in it.
                warnings.append({
                    "kind": "uncommitted_and_quiet",
                    "project": name,
                    "detail": (
                        f"{dirty_total} uncommitted file(s), no activity for "
                        f"{pulse_mod.humanize_duration(age)}"
                    ),
                })

    active.sort(key=lambda a: a["last_activity_age_sec"])
    quiet.sort(
        key=lambda q: (
            q["last_activity_age_sec"] is None,
            -(q["last_activity_age_sec"] or 0),
        )
    )

    return {
        "ok": True,
        "workspace": workspace_label,
        "generated_at": _now().isoformat(timespec="seconds"),
        "window_hours": since_hours,
        "project_count": len(pulses),
        "active": active,
        "quiet": quiet,
        "warnings": warnings,
        "quota": _quota_windows(quota) if quota is not None else None,
    }


def _quota_windows(quota: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the normalized quota snapshot into displayable windows."""
    out: list[dict[str, Any]] = []
    for agent, windows in (
        ("claude", ("five_hour", "seven_day")),
        ("codex", ("primary", "secondary")),
    ):
        entry = quota.get(agent) or {}
        for key in windows:
            w = entry.get(key) or {}
            pct = w.get("used_pct")
            if pct is None:
                continue
            out.append({
                "agent": agent,
                "window": key,
                "used_pct": pct,
                "resets_in": w.get("resets_in"),
            })
    return out


_WINDOW_LABELS = {
    "five_hour": "5h", "seven_day": "7d",
    "primary": "5h", "secondary": "wk",
}


def _pct_mark(pct: float) -> str:
    if pct >= 90:
        return "🔴"
    if pct >= 50:
        return "🟡"
    return "🟢"


def render(d: dict[str, Any]) -> str:
    """Render one digest dict as the markdown callers forward verbatim."""
    date = (d.get("generated_at") or "")[:10]
    hours = d.get("window_hours")
    span = f"last {hours}h" if hours != 168 else "last 7d"
    lines = [
        f"## 📊 Portfolio digest — {date} ({d.get('workspace')})",
        f"_{span} · {d.get('project_count')} project(s) · "
        f"{len(d.get('active') or [])} active_",
        "",
    ]

    active = d.get("active") or []
    if active:
        lines.append("**Active**")
        for a in active:
            bits: list[str] = []
            if a.get("commits"):
                n = f"{a['commits']}{'+' if a.get('commits_capped') else ''}"
                bits.append(f"{n} commit(s)")
            if a.get("dispatch_ok") or a.get("dispatch_failed"):
                bits.append(f"dispatches ✅{a['dispatch_ok']}/❌{a['dispatch_failed']}")
            if a.get("in_flight"):
                bits.append(f"⏳{a['in_flight']} in flight")
            if a.get("dirty"):
                bits.append(f"{a['dirty']} uncommitted")
            head = f"- **{a['project']}**"
            if a.get("branch"):
                head += f" `{a['branch']}`"
            lines.append(f"{head} — {', '.join(bits) if bits else 'session activity only'}")
            if a.get("latest_subject"):
                lines.append(f"    - latest: {a['latest_subject']}")
        lines.append("")
    else:
        lines += ["_No project activity in this window._", ""]

    warnings = d.get("warnings") or []
    if warnings:
        lines.append("**Warnings**")
        for w in warnings:
            lines.append(f"- ⚠️ {w['project']}: {w['detail']}")
        lines.append("")

    quiet = d.get("quiet") or []
    if quiet:
        oldest = quiet[0]
        oldest_txt = (
            pulse_mod.humanize_age(oldest.get("last_activity_age_sec"))
            if oldest.get("last_activity_age_sec") is not None
            else "no recorded activity"
        )
        lines.append(
            f"**Quiet** — {len(quiet)} project(s) "
            f"(longest: {oldest['project']}, {oldest_txt})"
        )
        lines.append("")

    windows = d.get("quota")
    if windows:
        parts = [
            f"{w['agent']} {_WINDOW_LABELS.get(w['window'], w['window'])} "
            f"{_pct_mark(w['used_pct'])}{round(w['used_pct'])}%"
            for w in windows
        ]
        lines.append("**Quota** " + " · ".join(parts))

    return "\n".join(lines).rstrip() + "\n"
