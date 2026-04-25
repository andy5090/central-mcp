"""Agent quota fetchers + normalized snapshot for orchestrator tools.

The per-agent fetchers (`claude`, `codex`, `gemini`) speak the raw shape of
each provider's auth file / usage API. `snapshot()` reduces them to a
single LLM-friendly payload that `token_usage` returns alongside the raw
token tally so the orchestrator can see "where am I against the cap?"
without a second tool call.

A short module-level cache avoids hitting the Anthropic and OpenAI usage
endpoints on every `token_usage` invocation — orchestrators tend to poll.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from central_mcp.quota import claude as _claude
from central_mcp.quota import codex as _codex
from central_mcp.quota import gemini as _gemini

# Cache TTL chosen so that:
#   - Sub-minute polling within a single orchestrator turn doesn't hammer
#     the upstream usage APIs.
#   - The numbers stay current enough to be actionable (subscription
#     windows are 1h+ on every supported plan).
_CACHE_TTL = 60.0

_cache_lock = threading.Lock()
_cache_data: dict[str, Any] | None = None
_cache_at: float = 0.0


def _fmt_reset_secs(secs: float | int | None) -> str:
    if secs is None:
        return "?"
    try:
        s = int(secs)
    except (TypeError, ValueError):
        return "?"
    if s <= 0:
        return "now"
    h, rem = divmod(s, 3600)
    m = rem // 60
    if h >= 24:
        d, hh = divmod(h, 24)
        return f"{d}d{hh:02d}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _fmt_reset_iso(value: Any) -> str:
    if not value:
        return "?"
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return "?"
    secs = (ts - datetime.now(timezone.utc)).total_seconds()
    return _fmt_reset_secs(secs)


def _safe_pct(value: Any) -> float:
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return round(max(0.0, min(100.0, v)), 1)


def _normalize_claude(q: dict[str, Any] | None) -> dict[str, Any]:
    if q is None:
        return {"mode": "not_installed"}
    mode = q.get("mode")
    if mode == "api_key":
        return {"mode": "api_key", "note": "no subscription quota"}
    if mode == "error":
        return {"mode": "error", "error": q.get("error") or "unknown"}
    err = q.get("error")
    if err:
        return {"mode": "pro", "error": str(err)}
    raw = q.get("raw") or {}
    fh = raw.get("five_hour") or {}
    wd = raw.get("seven_day") or {}
    return {
        "mode": "pro",
        "five_hour": {
            "used_pct": _safe_pct((fh.get("utilization") or 0) * 100),
            "resets_in": _fmt_reset_iso(fh.get("resets_at")),
            "resets_at": fh.get("resets_at"),
        },
        "seven_day": {
            "used_pct": _safe_pct((wd.get("utilization") or 0) * 100),
            "resets_in": _fmt_reset_iso(wd.get("resets_at")),
            "resets_at": wd.get("resets_at"),
        },
    }


def _window_label(secs: int | None, fallback: str) -> str:
    if not secs:
        return fallback
    if secs >= 86400:
        return f"{secs // 86400}d"
    if secs >= 3600:
        return f"{secs // 3600}h"
    return f"{max(1, secs // 60)}m"


def _normalize_codex(q: dict[str, Any] | None) -> dict[str, Any]:
    if q is None:
        return {"mode": "not_installed"}
    mode = q.get("mode")
    if mode == "api_key":
        return {"mode": "api_key", "note": "no subscription quota"}
    if mode == "error":
        return {"mode": "error", "error": q.get("error") or "unknown"}
    err = q.get("error")
    if err:
        return {"mode": "chatgpt", "error": str(err)}
    raw = q.get("raw") or {}
    plan = raw.get("plan_type") or "chatgpt"
    rl = raw.get("rate_limit") or {}
    pw = rl.get("primary_window") or {}
    sw = rl.get("secondary_window") or {}
    return {
        "mode": "chatgpt",
        "plan": plan,
        "primary": {
            "window": _window_label(pw.get("limit_window_seconds"), "5h"),
            "used_pct": _safe_pct(pw.get("used_percent")),
            "resets_in": _fmt_reset_secs(pw.get("reset_after_seconds")),
        },
        "secondary": {
            "window": _window_label(sw.get("limit_window_seconds"), "1d"),
            "used_pct": _safe_pct(sw.get("used_percent")),
            "resets_in": _fmt_reset_secs(sw.get("reset_after_seconds")),
        },
    }


def _normalize_gemini(q: dict[str, Any] | None) -> dict[str, Any]:
    if q is None:
        return {"mode": "not_installed"}
    return {
        "mode": "auth_only",
        "auth_type": q.get("auth_type") or "unknown",
        "note": "Gemini exposes no quota API",
    }


def _do_snapshot() -> dict[str, Any]:
    """Fetch + normalize all three providers. Each isolated by try/except."""

    def _safe(fetcher, normalize):
        try:
            raw = fetcher()
        except Exception as exc:
            return {"mode": "error", "error": f"fetch failed: {exc}"}
        try:
            return normalize(raw)
        except Exception as exc:
            return {"mode": "error", "error": f"normalize failed: {exc}"}

    return {
        "claude": _safe(_claude.fetch, _normalize_claude),
        "codex":  _safe(_codex.fetch,  _normalize_codex),
        "gemini": _safe(_gemini.fetch, _normalize_gemini),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def snapshot(*, force: bool = False) -> dict[str, Any]:
    """Return a normalized per-agent quota snapshot, cached for 60s.

    `force=True` bypasses the cache (used by tests). The returned dict
    includes a `cached` flag so callers can tell whether the data is fresh.
    """
    global _cache_data, _cache_at
    now = time.time()
    with _cache_lock:
        cached = _cache_data is not None and (now - _cache_at) < _CACHE_TTL
        if cached and not force:
            data = dict(_cache_data)  # type: ignore[arg-type]
            data["cached"] = True
            return data

    data = _do_snapshot()
    with _cache_lock:
        _cache_data = data
        _cache_at = now
    out = dict(data)
    out["cached"] = False
    return out


def _reset_cache_for_tests() -> None:
    """Clear the module-level cache (test hook)."""
    global _cache_data, _cache_at
    with _cache_lock:
        _cache_data = None
        _cache_at = 0.0
