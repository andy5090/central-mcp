"""Fetch Codex quota from OpenAI's internal usage API.

Only works when Codex CLI is configured in "chatgpt" auth mode (ChatGPT account
login). API Key users have no subscription quota — returns {"mode": "api_key"}.
Returns None when Codex is not installed.
"""

from __future__ import annotations

import json
import ssl
import urllib.request
from pathlib import Path
from typing import Any

_USAGE_URL = "https://chatgpt.com/api/codex/usage"


def _auth_path() -> Path:
    return Path.home() / ".codex" / "auth.json"


_SENTINEL_UNREADABLE: dict[str, Any] = {"__unreadable__": True}


def _read_auth() -> dict[str, Any] | None:
    try:
        return json.loads(_auth_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return _SENTINEL_UNREADABLE


def fetch() -> dict[str, Any] | None:
    """Return Codex quota info, or None if Codex is not installed.

    Possible shapes:
      None                                — Codex not installed
      {"mode": "api_key"}                — API Key mode, no subscription quota
      {"mode": "error", "error": "..."}  — auth file unreadable/malformed
      {"mode": "chatgpt", "raw": {...}}  — ChatGPT mode, API succeeded
      {"mode": "chatgpt", "error": "..."} — ChatGPT mode, API failed
    """
    data = _read_auth()
    if data is None:
        return None  # Codex not installed
    if data.get("__unreadable__"):
        return {"mode": "error", "error": "~/.codex/auth.json unreadable"}

    mode = data.get("auth_mode", "apikey")
    if mode != "chatgpt":
        return {"mode": "api_key"}

    tokens = data.get("tokens") or {}
    if isinstance(tokens, str):
        try:
            tokens = json.loads(tokens)
        except Exception:
            tokens = {}

    access_token = (
        tokens.get("accessToken")
        or tokens.get("access_token")
        or data.get("accessToken")
    )
    account_id = (
        tokens.get("accountId")
        or tokens.get("account_id")
        or data.get("account_id")
        or ""
    )

    if not access_token:
        return {"mode": "chatgpt", "error": "no access token in ~/.codex/auth.json"}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id

    try:
        req = urllib.request.Request(_USAGE_URL, headers=headers)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            return {"mode": "chatgpt", "raw": json.loads(resp.read())}
    except Exception as exc:
        return {"mode": "chatgpt", "error": str(exc)}
