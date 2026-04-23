"""Fetch Claude Code quota from Anthropic's OAuth usage API.

Works for Claude Code Pro/Team/Enterprise users who authenticated via OAuth.
API Key users have no subscription quota — returns {"mode": "api_key"}.
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from pathlib import Path
from typing import Any

_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_BETA_HEADER = "oauth-2025-04-20"


def _cred_path() -> Path:
    return Path.home() / ".claude" / ".credentials.json"


_UNREADABLE = object()


def _read_token() -> Any:
    """Read OAuth access token from ~/.claude/.credentials.json.

    Returns the token string, None (no token / file missing), or the
    _UNREADABLE sentinel when the file exists but is malformed.
    """
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
    # Credentials may be nested under "claudeAiOauth" or at root level.
    creds = data.get("claudeAiOauth") or data if isinstance(data, dict) else {}
    if not isinstance(creds, dict):
        return _UNREADABLE
    return creds.get("accessToken") or creds.get("access_token")


def fetch() -> dict[str, Any]:
    """Return Claude quota info.

    Possible shapes:
      {"mode": "api_key"}                — no OAuth creds found
      {"mode": "error", "error": "..."}  — credentials file unreadable/malformed
      {"mode": "pro", "raw": {...}}      — API call succeeded
      {"mode": "pro", "error": "..."}   — API call failed
    """
    token = _read_token()
    if token is _UNREADABLE:
        return {"mode": "error", "error": "~/.claude/.credentials.json unreadable"}
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
