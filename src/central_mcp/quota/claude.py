"""Fetch Claude Code quota from Anthropic's OAuth usage API.

Works for Claude Code Pro/Team/Enterprise users who authenticated via
OAuth. API Key users have no subscription quota — returns
``{"mode": "api_key"}``.

Storage: Claude Code persists OAuth credentials in
``~/.claude/.credentials.json`` on Linux/Windows, but on macOS the
recent CLI uses the user keychain (``Claude Code-credentials``)
instead. Both are checked transparently so subscription users on
either platform get real quota numbers.
"""

from __future__ import annotations

import json
import platform
import ssl
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"
_KEYCHAIN_SERVICE = "Claude Code-credentials"


def _cred_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


_UNREADABLE = object()


def _extract_access_token(payload: Any) -> Any:
    """Pull an access token out of a parsed credentials blob.

    Returns the string, None (token absent), or _UNREADABLE
    (structure isn't a dict-of-dict).
    """
    if not isinstance(payload, dict):
        return _UNREADABLE
    creds = payload.get("claudeAiOauth") or payload
    if not isinstance(creds, dict):
        return _UNREADABLE
    return creds.get("accessToken") or creds.get("access_token")


def _read_token_from_file() -> Any:
    path = _cred_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:
        return _UNREADABLE
    try:
        data = json.loads(raw)
    except Exception:
        return _UNREADABLE
    return _extract_access_token(data)


def _read_token_from_keychain() -> Any:
    """macOS keychain fallback — Claude Code stores credentials under
    the generic-password service `Claude Code-credentials`. Returns
    None on non-macOS, missing entry, or any subprocess failure;
    `_UNREADABLE` when the entry exists but isn't valid JSON.
    """
    if platform.system() != "Darwin":
        return None
    try:
        r = subprocess.run(
            ["security", "find-generic-password",
             "-s", _KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    raw = r.stdout.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return _UNREADABLE
    return _extract_access_token(data)


def _read_token() -> Any:
    """Read OAuth access token. Returns the token string, None (no
    creds found anywhere), or the `_UNREADABLE` sentinel when a source
    exists but is malformed.

    Resolution order: file (`~/.claude/.credentials.json`) → macOS
    keychain (`security find-generic-password -s "Claude
    Code-credentials"`). The keychain branch is a no-op on
    Linux/Windows.
    """
    file_token = _read_token_from_file()
    if file_token is not None and file_token is not _UNREADABLE:
        return file_token
    if file_token is _UNREADABLE:
        return _UNREADABLE
    # File missing → try macOS keychain.
    return _read_token_from_keychain()


def fetch() -> dict[str, Any]:
    """Return Claude quota info.

    Possible shapes:
      {"mode": "api_key"}                — no OAuth creds anywhere
      {"mode": "error", "error": "..."}  — creds source unreadable/malformed
      {"mode": "pro", "raw": {...}}      — API call succeeded
      {"mode": "pro", "error": "..."}   — API call failed
    """
    token = _read_token()
    if token is _UNREADABLE:
        return {"mode": "error", "error": "Claude Code credentials unreadable"}
    if not token:
        return {"mode": "api_key"}

    try:
        req = urllib.request.Request(
            _USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": _BETA_HEADER,
            },
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            return {"mode": "pro", "raw": json.loads(resp.read())}
    except Exception as exc:
        return {"mode": "pro", "error": str(exc)}
