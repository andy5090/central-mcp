"""`central-mcp monitor` — portfolio-wide agent quota + dispatch stats dashboard.

Displays a curses-based live dashboard with two sections:

  AGENT QUOTA   — Claude Code and Codex subscription quota bars (OAuth users).
                  API Key users see "no subscription quota". Gemini has no
                  quota API so only auth-type is shown.

  DISPATCH STATS — Per-project token totals and dispatch counts for today (UTC),
                   read from ~/.central-mcp/timeline.jsonl.

Quota is refreshed every 90 seconds in a background thread. Stats refresh
every 10 seconds. Press q / ESC / Ctrl+C to exit.
"""

from __future__ import annotations

import curses
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from central_mcp import events
from central_mcp.events import token_total
from central_mcp.quota import claude as _claude
from central_mcp.quota import codex as _codex
from central_mcp.quota import gemini as _gemini
from central_mcp.registry import load_registry

_QUOTA_TTL = 90.0   # seconds between quota API polls
_STATS_TTL = 10.0   # seconds between timeline re-reads
_REDRAW_HZ = 0.5    # curses redraw interval (seconds)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_reset(value: Any) -> str:
    """Format 'Xh Ym' or 'Ym' until reset from an ISO timestamp or seconds."""
    try:
        if isinstance(value, (int, float)):
            secs = float(value)
        else:
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            secs = (ts - datetime.now(timezone.utc)).total_seconds()
        if secs <= 0:
            return "now"
        h, rem = divmod(int(secs), 3600)
        m = rem // 60
        return f"{h}h{m:02d}m" if h else f"{m}m"
    except Exception:
        return "?"


def _safe_pct(value: Any) -> float:
    """Coerce an API value into a 0–100 float; 0.0 on None/NaN/junk."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(0.0, min(100.0, v))


def _bar(pct: float, width: int = 10) -> str:
    filled = round(_safe_pct(pct) / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _pct_attr(pct: float) -> int:
    p = _safe_pct(pct)
    if p >= 90:
        return curses.color_pair(3) | curses.A_BOLD
    if p >= 70:
        return curses.color_pair(4) | curses.A_BOLD
    return curses.color_pair(2)


def _fmt_age(fetched_at: float) -> str:
    """Format elapsed seconds since a wall-clock timestamp."""
    if not fetched_at:
        return "—"
    secs = int(time.time() - fetched_at)
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"


def _fmt_last(ts_iso: str | None) -> str:
    if not ts_iso:
        return "—"
    try:
        ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - ts).total_seconds()
        if secs < 60:
            return f"{int(secs)}s ago"
        if secs < 3600:
            return f"{int(secs / 60)}m ago"
        return f"{int(secs / 3600)}h ago"
    except Exception:
        return "?"


def _truncate(text: str, width: int) -> str:
    """Truncate with ellipsis if over width. width must be >= 1."""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


# ── Quota cache ───────────────────────────────────────────────────────────────

class _QuotaCache:
    """Thread-safe cache around the quota fetchers.

    `get()` returns a shallow copy — inner dicts (`raw`, `five_hour`, …) are
    shared with the writer. This is safe today because `_do_fetch` always
    assigns a freshly-constructed dict and never mutates inner state after
    assignment. If that invariant ever changes, switch to a deep copy.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._fetched_at: float = 0.0
        self._fetching: bool = False

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def fetched_at(self) -> float:
        with self._lock:
            return self._fetched_at

    def is_fetching(self) -> bool:
        with self._lock:
            return self._fetching

    def needs_refresh(self) -> bool:
        with self._lock:
            stale = (time.time() - self._fetched_at) >= _QUOTA_TTL
            return stale and not self._fetching

    def begin_fetch(self) -> None:
        with self._lock:
            self._fetching = True

    def abort_fetch(self) -> None:
        """Release the fetching flag without updating data (for spawn failure)."""
        with self._lock:
            self._fetching = False

    def set(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._data = data
            self._fetched_at = time.time()
            self._fetching = False

    def mark_fetched(self) -> None:
        """Record a fetch attempt without overwriting prior data (used on error)."""
        with self._lock:
            self._fetched_at = time.time()
            self._fetching = False


_cache = _QuotaCache()


def _do_fetch() -> None:
    """Refresh all three quota fetchers. Preserves prior data on error."""
    try:
        data = {
            "claude": _claude.fetch(),
            "codex":  _codex.fetch(),
            "gemini": _gemini.fetch(),
        }
        _cache.set(data)
    except Exception:
        # Preserve prior _data so the UI shows last-known-good values
        # instead of blanking out on a transient error.
        _cache.mark_fetched()


def _spawn_fetch() -> None:
    _cache.begin_fetch()
    try:
        threading.Thread(target=_do_fetch, daemon=True).start()
    except Exception:
        # If we can't even spawn the thread, release the lock so the
        # next tick retries instead of sticking in "fetching" forever.
        _cache.abort_fetch()


# ── Dispatch stats ────────────────────────────────────────────────────────────

def _load_today_stats() -> dict[str, dict[str, Any]]:
    """Aggregate today's (UTC) per-project stats from the global timeline.

    Reads the timeline in reverse and stops at the first record older than
    midnight UTC — avoids re-parsing unbounded history on each refresh.
    """
    path = events.timeline_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    lines = raw.splitlines()
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    stats: dict[str, dict[str, Any]] = {}

    for ln in reversed(lines):
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        try:
            ts = datetime.fromisoformat(r.get("ts", "").replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < midnight:
            break  # everything earlier is also < midnight

        proj = r.get("project", "?")
        s = stats.setdefault(proj, {
            "dispatches": 0,
            "tokens_total": 0,
            "last_ts": None,
            "last_ok": None,
            "agent": "",
        })

        evt = r.get("event")
        if evt == "dispatched":
            s["dispatches"] += 1
        elif evt in ("complete", "error"):
            # Reverse iteration: the *first* complete/error we see is the
            # most recent one. Preserve it rather than overwriting later.
            if s["last_ts"] is None:
                s["last_ts"] = r.get("ts")
                s["last_ok"] = r.get("ok", False)
                s["agent"] = r.get("agent") or s["agent"]
            s["tokens_total"] += token_total(r.get("tokens"))

    return stats


# ── Curses rendering ──────────────────────────────────────────────────────────

def _wstr(win: "curses.window", row: int, col: int, text: str, attr: int = 0) -> None:
    try:
        win.addstr(row, col, text, attr)
    except curses.error:
        pass


def _render_claude(win: "curses.window", row: int, q: dict | None, cols: int) -> int:
    if q is None:
        return 0
    mode = q.get("mode", "api_key")
    if mode == "api_key":
        _wstr(win, row, 0, " claude  [API Key]  no subscription quota", curses.A_DIM)
        return 1
    if mode == "error":
        msg = (q.get("error") or "auth file unreadable")[:60]
        _wstr(win, row, 0, f" claude  [?]  ⚠ {msg}", curses.color_pair(3))
        return 1

    err = q.get("error")
    if err:
        _wstr(win, row, 0, f" claude  [Pro]  ⚠ {str(err)[:60]}", curses.color_pair(3))
        return 1

    raw = q.get("raw") or {}
    fh = raw.get("five_hour") or {}
    wd = raw.get("seven_day") or {}
    fh_pct = _safe_pct((fh.get("utilization") or 0) * 100)
    wd_pct = _safe_pct((wd.get("utilization") or 0) * 100)
    fh_reset = _fmt_reset(fh.get("resets_at", ""))
    wd_reset = _fmt_reset(wd.get("resets_at", ""))

    try:
        win.addstr(row, 0, " claude  [Pro]  ", curses.A_BOLD)
        win.addstr("5h:", curses.A_DIM)
        win.addstr(_bar(fh_pct), _pct_attr(fh_pct))
        win.addstr(f" {fh_pct:3.0f}%  reset {fh_reset:<8}", curses.A_DIM)
        win.addstr("│  wk:", curses.A_DIM)
        win.addstr(_bar(wd_pct), _pct_attr(wd_pct))
        win.addstr(f" {wd_pct:3.0f}%  reset {wd_reset}", curses.A_DIM)
    except curses.error:
        pass
    return 1


def _render_codex(win: "curses.window", row: int, q: dict | None, cols: int) -> int:
    if q is None:
        return 0
    mode = q.get("mode", "api_key")
    if mode == "api_key":
        _wstr(win, row, 0, " codex   [API Key]  no subscription quota", curses.A_DIM)
        return 1
    if mode == "error":
        msg = (q.get("error") or "auth file unreadable")[:60]
        _wstr(win, row, 0, f" codex   [?]  ⚠ {msg}", curses.color_pair(3))
        return 1

    err = q.get("error")
    if err:
        _wstr(win, row, 0, f" codex   [ChatGPT]  ⚠ {str(err)[:60]}", curses.color_pair(3))
        return 1

    raw = q.get("raw") or {}
    plan = raw.get("plan_type", "chatgpt")
    rl = raw.get("rate_limit") or {}
    pw = rl.get("primary_window") or {}
    sw = rl.get("secondary_window") or {}
    pw_pct = _safe_pct(pw.get("used_percent", 0))
    sw_pct = _safe_pct(sw.get("used_percent", 0))
    pw_secs = pw.get("limit_window_seconds") or 3600
    sw_secs = sw.get("limit_window_seconds") or 86400
    pw_label = "1h" if pw_secs <= 3600 else f"{pw_secs//3600}h"
    sw_label = "1d" if sw_secs >= 86400 else f"{sw_secs//3600}h"
    pw_reset = _fmt_reset(pw.get("reset_after_seconds", 0))
    sw_reset = _fmt_reset(sw.get("reset_after_seconds", 0))

    try:
        win.addstr(row, 0, f" codex   [{plan}]  ", curses.A_BOLD)
        win.addstr(f"{pw_label}:", curses.A_DIM)
        win.addstr(_bar(pw_pct), _pct_attr(pw_pct))
        win.addstr(f" {pw_pct:3.0f}%  reset {pw_reset:<8}", curses.A_DIM)
        win.addstr("│  ")
        win.addstr(f"{sw_label}:", curses.A_DIM)
        win.addstr(_bar(sw_pct), _pct_attr(sw_pct))
        win.addstr(f" {sw_pct:3.0f}%  reset {sw_reset}", curses.A_DIM)
    except curses.error:
        pass
    return 1


def _render_gemini(win: "curses.window", row: int, q: dict | None, cols: int) -> int:
    if q is None:
        return 0
    auth = q.get("auth_type", "unknown")
    _wstr(win, row, 0, f" gemini  [{auth}]  no quota API available", curses.A_DIM)
    return 1


def _draw(
    stdscr: "curses.window",
    quota: dict[str, Any],
    quota_fetched_at: float,
    quota_fetching: bool,
    stats: dict[str, dict],
    projects: list[str],
    stats_fetched_at: float,
) -> None:
    rows, cols = stdscr.getmaxyx()
    stdscr.erase()
    row = 0

    # ── Title bar ──
    if quota_fetched_at == 0 and quota_fetching:
        quota_age_str = "quota: fetching…"
    else:
        quota_age_str = f"quota: {_fmt_age(quota_fetched_at)}"
    stats_age_str = f"stats: {_fmt_age(stats_fetched_at)}"

    title = f" central-mcp monitor  │  {quota_age_str}  │  {stats_age_str}  │  q: quit"
    _wstr(stdscr, row, 0, title[: cols - 1], curses.A_BOLD | curses.color_pair(1))
    row += 1
    _wstr(stdscr, row, 0, "─" * (cols - 1), curses.A_DIM)
    row += 1

    # ── Agent quota ──
    _wstr(stdscr, row, 0, " AGENT QUOTA", curses.A_BOLD)
    row += 1
    row += _render_claude(stdscr, row, quota.get("claude"), cols)
    row += _render_codex(stdscr, row, quota.get("codex"), cols)
    row += _render_gemini(stdscr, row, quota.get("gemini"), cols)
    row += 1
    _wstr(stdscr, row, 0, "─" * (cols - 1), curses.A_DIM)
    row += 1

    # ── Dispatch stats ──
    total_tokens = sum(s.get("tokens_total", 0) for s in stats.values())
    header = f" DISPATCH STATS (today UTC)  total tokens: {total_tokens:,}"
    _wstr(stdscr, row, 0, header[: cols - 1], curses.A_BOLD)
    row += 1

    col_hdr = f" {'project':<22} {'agent':<10} {'runs':>5}  {'tokens':>9}  last"
    _wstr(stdscr, row, 0, col_hdr[: cols - 1], curses.A_DIM)
    row += 1

    # Projects with activity first (in registry order), then active but not registered.
    ordered = [p for p in projects if p in stats] + [
        p for p in sorted(stats) if p not in projects
    ]
    shown: set[str] = set()
    for proj in ordered:
        if row >= rows - 1:
            break
        s = stats.get(proj, {})
        agent  = _truncate(s.get("agent") or "?", 10)
        runs   = s.get("dispatches", 0)
        tokens = s.get("tokens_total", 0)
        last   = _fmt_last(s.get("last_ts"))
        ok     = s.get("last_ok")
        badge  = "✓" if ok is True else ("✗" if ok is False else " ")
        tok_s  = f"{tokens:,}" if tokens else "—"
        line   = f" {_truncate(proj, 22):<22} {agent:<10} {runs:>5}  {tok_s:>9}  {last} {badge}"
        attr   = (curses.color_pair(2) if ok is True
                  else curses.color_pair(3) if ok is False else 0)
        _wstr(stdscr, row, 0, line[: cols - 1], attr)
        row += 1
        shown.add(proj)

    # Registered projects with no activity today
    for proj in projects:
        if proj in shown or row >= rows - 1:
            continue
        line = f" {_truncate(proj, 22):<22} {'—':<10} {'0':>5}  {'—':>9}  no activity today"
        _wstr(stdscr, row, 0, line[: cols - 1], curses.A_DIM)
        row += 1

    stdscr.noutrefresh()
    curses.doupdate()


# ── Main loop ─────────────────────────────────────────────────────────────────

def _main(stdscr: "curses.window", projects: list[str]) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)

    _spawn_fetch()  # kick off initial quota poll

    stats: dict[str, dict] = {}
    stats_fetched_at: float = 0.0
    last_draw: float = 0.0

    while True:
        now = time.time()

        if _cache.needs_refresh():
            _spawn_fetch()

        if now - stats_fetched_at >= _STATS_TTL:
            stats = _load_today_stats()
            stats_fetched_at = now

        if now - last_draw >= _REDRAW_HZ:
            _draw(
                stdscr,
                _cache.get(),
                _cache.fetched_at(),
                _cache.is_fetching(),
                stats,
                projects,
                stats_fetched_at,
            )
            last_draw = now

        key = stdscr.getch()
        if key in (ord("q"), ord("Q"), 27, 3):
            break
        # KEY_RESIZE is handled implicitly — _draw re-queries getmaxyx() each
        # frame and erase()s before rendering, so no explicit clear is needed.

        time.sleep(0.05)


def run() -> int:
    """Launch the monitor dashboard. Blocks until q / ESC / Ctrl+C."""
    try:
        projects = [p.name for p in load_registry()]
    except Exception:
        projects = []

    try:
        curses.wrapper(_main, projects)
    except KeyboardInterrupt:
        pass
    return 0
