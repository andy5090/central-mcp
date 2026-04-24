"""User config persisted at `~/.central-mcp/config.toml`.

Flat per-user settings keyed by top-level TOML tables:

  [orchestrator]
  default = "claude"            # which CLI `central-mcp run` launches

  [user]
  timezone          = "Asia/Seoul"   # IANA tz for date-boundary display
  current_workspace = "default"      # active workspace

Reads are best-effort (return defaults on missing/malformed). Writes go
through `tomlkit` so comments and ordering are preserved.

`ensure_initialized()` is the idempotent bootstrap path called on every
install/upgrade/startup: it injects the system timezone + default
workspace when those fields are absent, and migrates `current_workspace`
out of `registry.yaml` (where it used to live) into this file.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import tomlkit

from central_mcp import paths


# ── timezone helpers ──────────────────────────────────────────────────────────

def _system_timezone() -> str:
    """Best-effort IANA name for the system local timezone.

    Resolution order:
      1. `$TZ` if it already looks IANA (e.g. 'Asia/Seoul').
      2. Resolved target of `/etc/localtime` — canonical on Linux/macOS/WSL.
      3. `UTC` as final fallback (Windows native or misconfigured hosts).
    """
    tz = os.environ.get("TZ", "").strip()
    if tz and not tz.startswith(":") and "/" in tz:
        return tz
    try:
        link = Path("/etc/localtime")
        if link.exists():
            resolved = str(link.resolve())
            marker = "/zoneinfo/"
            if marker in resolved:
                return resolved.split(marker, 1)[1]
    except Exception:
        pass
    return "UTC"


# ── low-level read/write ──────────────────────────────────────────────────────

def _read() -> tomlkit.TOMLDocument:
    try:
        return tomlkit.parse(paths.config_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return tomlkit.document()
    except Exception:
        return tomlkit.document()


def _write(doc: tomlkit.TOMLDocument) -> None:
    paths.central_mcp_home().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text(tomlkit.dumps(doc), encoding="utf-8")


def _get_table(doc: tomlkit.TOMLDocument, name: str) -> Any:
    table = doc.get(name)
    if table is None:
        table = tomlkit.table()
        doc[name] = table
    return table


# ── timezone ──────────────────────────────────────────────────────────────────

def orchestrator_default() -> str | None:
    """Return `[orchestrator].default` from config.toml, or None if unset.

    Used by `central-mcp run` to decide which CLI to launch, and by
    `orch_session.sync_orchestrator` to know which session files to scan
    for per-turn token usage.
    """
    orch = _read().get("orchestrator") or {}
    val = orch.get("default")
    return str(val) if val else None


def upgrade_check_enabled() -> bool:
    """Whether `central-mcp run` / `central-mcp up` should probe PyPI on
    launch for a newer release. Default: True. Turn off with
    `[user].upgrade_check_enabled = false` in config.toml — e.g. on
    restricted networks or in CI.
    """
    user = _read().get("user") or {}
    v = user.get("upgrade_check_enabled")
    return True if v is None else bool(v)


def upgrade_check_interval_hours() -> int:
    """Minimum hours between PyPI version probes. Default: 24."""
    user = _read().get("user") or {}
    try:
        return max(1, int(user.get("upgrade_check_interval_hours") or 24))
    except (TypeError, ValueError):
        return 24


def upgrade_last_checked_at() -> str | None:
    user = _read().get("user") or {}
    val = user.get("upgrade_last_checked_at")
    return str(val) if val else None


def set_upgrade_last_checked_at(ts_iso: str) -> None:
    doc = _read()
    _get_table(doc, "user")["upgrade_last_checked_at"] = ts_iso
    _write(doc)


def orchestrator_fallback_enabled() -> bool:
    """Whether `central-mcp run` should automatically try other installed
    orchestrators when the primary is over quota. Default: True.
    """
    orch = _read().get("orchestrator") or {}
    v = orch.get("fallback_enabled")
    return True if v is None else bool(v)


def orchestrator_fallback() -> list[str]:
    """Optional user-supplied fallback order. Empty list means "auto"
    (every other installed orchestrator-capable agent, discovery order).
    """
    orch = _read().get("orchestrator") or {}
    val = orch.get("fallback")
    if isinstance(val, list):
        return [str(x) for x in val]
    return []


_QUOTA_DEFAULTS = {"five_hour": 95, "seven_day": 90}


def quota_threshold() -> dict[str, int]:
    """`five_hour` / `seven_day` percent thresholds. An orchestrator
    whose current provider-reported utilization meets or exceeds either
    threshold is skipped by the fallback chain.
    """
    orch = _read().get("orchestrator") or {}
    cfg = orch.get("quota_threshold") or {}
    return {
        "five_hour": int(cfg.get("five_hour") or _QUOTA_DEFAULTS["five_hour"]),
        "seven_day": int(cfg.get("seven_day") or _QUOTA_DEFAULTS["seven_day"]),
    }


def user_timezone() -> str:
    """Return the user's configured timezone; fall back to system, then UTC."""
    user = _read().get("user") or {}
    tz = str(user.get("timezone") or "").strip()
    return tz or _system_timezone()


def set_user_timezone(tz: str) -> None:
    doc = _read()
    _get_table(doc, "user")["timezone"] = tz
    _write(doc)


# ── workspace ─────────────────────────────────────────────────────────────────

def current_workspace() -> str:
    """Return the active workspace name (default: 'default')."""
    user = _read().get("user") or {}
    return str(user.get("current_workspace") or "default")


def set_current_workspace(name: str) -> None:
    """Set the active workspace. Raises ValueError if it's not registered."""
    # Import locally to avoid registry ↔ config cycles at module load.
    from central_mcp.registry import load_workspaces
    workspaces = load_workspaces()
    if workspaces and name not in workspaces:
        raise ValueError(f"unknown workspace {name!r}")
    doc = _read()
    _get_table(doc, "user")["current_workspace"] = name
    _write(doc)


# ── bootstrap ─────────────────────────────────────────────────────────────────

def ensure_initialized() -> bool:
    """Idempotently seed `[user].timezone` and `[user].current_workspace`.

    Safe to call on every startup. Also performs a one-shot migration of
    `current_workspace` out of `registry.yaml` (its legacy home) into
    `config.toml`. Returns True if any change was persisted.
    """
    doc = _read()
    user = _get_table(doc, "user")
    changed = False

    # Try to lift a legacy current_workspace value out of registry.yaml.
    # Done before injecting defaults so the user's prior choice wins over
    # the "default" placeholder.
    legacy_ws: str | None = None
    try:
        from central_mcp.registry import _read_raw, _write_raw  # type: ignore
        raw = _read_raw()
        if raw and "current_workspace" in raw:
            legacy_ws = str(raw.get("current_workspace") or "") or None
            del raw["current_workspace"]
            _write_raw(raw)
            changed = True
    except Exception:
        pass

    if "current_workspace" not in user:
        user["current_workspace"] = legacy_ws or "default"
        changed = True
    elif legacy_ws and user.get("current_workspace") == "default":
        # Config already exists but only with the placeholder — honor the
        # legacy value we just lifted.
        user["current_workspace"] = legacy_ws
        changed = True

    if "timezone" not in user:
        user["timezone"] = _system_timezone()
        changed = True

    if changed:
        _write(doc)
    return changed
