"""Asyncio watcher — reads `dispatches.db` + `tokens.db` and pushes
updates into the sidebar widgets.

Cadence:
- dispatches list refresh: every 1s, but only when the SQLite file's
  mtime has actually changed (cheap stat() check first).
- token HUD refresh: every 15s on the same loop tick.

Completion notifications fire via `App.notify()` for any dispatch that
transitions into a terminal state (`complete` / `error` / `cancelled` /
`timeout`) since the previous tick. The first tick is suppressed so
opening the TUI doesn't spam toasts for every historical entry.
"""
from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text

from central_mcp import config as user_config
from central_mcp import dispatches_db, tokens_db
from central_mcp.quota.render import render_summary


_TERMINAL_STATES = frozenset({"complete", "error", "cancelled", "timeout"})


class DispatchWatcher:
    def __init__(
        self,
        app,
        sidebar,
        *,
        dispatch_interval: float = 1.0,
        token_interval: float = 15.0,
    ) -> None:
        self.app = app
        self.sidebar = sidebar
        self.dispatch_interval = dispatch_interval
        self.token_interval = token_interval
        self._task: asyncio.Task | None = None
        self._last_db_mtime: float | None = None
        self._known_terminal: dict[str, str] = {}
        self._next_token_refresh = 0.0

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        try:
            self._refresh_dispatches(initial=True)
            await self._refresh_token_hud()
            while True:
                await asyncio.sleep(self.dispatch_interval)
                self._refresh_dispatches()
                if asyncio.get_event_loop().time() >= self._next_token_refresh:
                    await self._refresh_token_hud()
        except asyncio.CancelledError:
            pass

    # ── dispatches ───────────────────────────────────────────────────

    def _refresh_dispatches(self, *, initial: bool = False) -> None:
        path = dispatches_db.db_path()
        try:
            mtime: float | None = path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        if not initial and mtime is not None and mtime == self._last_db_mtime:
            return
        self._last_db_mtime = mtime

        try:
            active = dispatches_db.list_active()
        except Exception:
            active = []
        try:
            recent = [
                d for d in dispatches_db.list_all(20)
                if d.get("status") != "running"
            ][:5]
        except Exception:
            recent = []

        self._fire_completion_notifications(recent, suppress=initial)
        try:
            self.sidebar.dispatch_list.update_dispatches(active, recent)
        except Exception:
            pass

    def _fire_completion_notifications(
        self,
        recent: list[dict[str, Any]],
        *,
        suppress: bool,
    ) -> None:
        new_terminal = {
            d["id"]: (d.get("status") or "")
            for d in recent
            if d.get("id") and (d.get("status") or "") in _TERMINAL_STATES
        }
        if not suppress:
            for did, status in new_terminal.items():
                if did in self._known_terminal:
                    continue
                entry = next((d for d in recent if d.get("id") == did), {})
                project = entry.get("project") or "?"
                severity = "error" if status == "error" else "information"
                try:
                    self.app.notify(
                        f"{project}: {status}",
                        title="dispatch",
                        severity=severity,
                    )
                except Exception:
                    pass
        self._known_terminal = new_terminal

    # ── token HUD ────────────────────────────────────────────────────

    async def _refresh_token_hud(self) -> None:
        loop = asyncio.get_event_loop()
        self._next_token_refresh = loop.time() + self.token_interval
        try:
            text = await loop.run_in_executor(None, _build_token_summary)
        except Exception as exc:
            text = f"Tokens · refresh failed: {exc!s}"
        try:
            self.sidebar.token_hud.update(Text(text))
        except Exception:
            pass


# ── token summary helpers ────────────────────────────────────────────

def _build_token_summary() -> str:
    """Compose the token-HUD text. Returns the inner ```text``` body of
    `quota.render.render_summary` — the markdown chrome (`**…**` + fences)
    is stripped so the sidebar's own borders don't double up.
    """
    tz = user_config.user_timezone()
    agg = tokens_db.aggregate(
        period="today",
        tz_str=tz,
        project_filter=None,
        group_by="project",
    )
    result: dict[str, Any] = {
        "ok": True,
        "period": "today",
        "timezone": tz,
        "window": agg["window"],
        "group_by": "project",
        "breakdown": agg["breakdown"],
        "total": agg["total"],
    }
    try:
        from central_mcp import quota as _quota
        result["quota"] = _quota.snapshot()
    except Exception:
        pass
    try:
        agent_totals: dict[str, dict[str, int]] = {}
        for window_key in ("today", "week"):
            sub = tokens_db.aggregate(
                period=window_key,
                tz_str=tz,
                project_filter=None,
                group_by="agent",
            )
            for name, slice_ in (sub.get("breakdown") or {}).items():
                bucket = agent_totals.setdefault(
                    name, {"today": 0, "week": 0}
                )
                bucket[window_key] = int((slice_ or {}).get("total") or 0)
        if agent_totals:
            result["agent_totals"] = agent_totals
    except Exception:
        pass
    return strip_summary_chrome(render_summary(result))


def strip_summary_chrome(md: str) -> str:
    """Strip the leading `**title**` line and the surrounding ```text```
    fences so only the formatted body remains. Falls back to the input
    if the structure doesn't match what render_summary produces.
    """
    lines = md.splitlines()
    body_start = -1
    for i, ln in enumerate(lines[:4]):
        if ln.startswith("```text"):
            body_start = i + 1
            break
    if body_start < 0:
        return md
    body_end = len(lines)
    for i in range(len(lines) - 1, body_start - 1, -1):
        if lines[i].strip() == "```":
            body_end = i
            break
    if body_end <= body_start:
        return md
    return "\n".join(lines[body_start:body_end])
