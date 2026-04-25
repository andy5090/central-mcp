"""Fetch Codex quota from OpenAI's internal usage API.

Only works when Codex CLI is configured in "chatgpt" auth mode (ChatGPT
account login). API Key users have no subscription quota — returns
``{"mode": "api_key"}``. Returns None when Codex is not installed.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
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


def _try_call(token: str, account_id: str) -> tuple[dict[str, Any] | None, Exception | None]:
    """Hit the usage API with the given bearer token. Returns (json, None)
    on success, (None, exception) on failure. The 403 case is the
    common "wrong-token-type" signal we use to drive the id-token
    fallback in `fetch()`.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    try:
        req = urllib.request.Request(_USAGE_URL, headers=headers)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            return json.loads(resp.read()), None
    except Exception as exc:
        return None, exc


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

    # Newer codex CLIs persist tokens under snake_case keys; older
    # builds used camelCase. Both shapes are checked.
    id_token = (
        tokens.get("id_token")
        or tokens.get("idToken")
    )
    access_token = (
        tokens.get("access_token")
        or tokens.get("accessToken")
        or data.get("accessToken")
    )
    account_id = (
        tokens.get("account_id")
        or tokens.get("accountId")
        or data.get("account_id")
        or ""
    )

    if not (id_token or access_token):
        return {"mode": "chatgpt", "error": "no token in ~/.codex/auth.json"}

    # The chatgpt.com /api/codex/usage endpoint accepts the OAuth
    # id_token as the Bearer credential in current CLI versions; older
    # builds used the access_token. Try id_token first when present,
    # fall back to access_token on auth failure (HTTP 401/403). Other
    # errors (timeout, 5xx, JSON decode) surface immediately so the
    # caller sees the real problem instead of a silent retry.
    last_err: Exception | None = None
    for tok in (id_token, access_token):
        if not tok:
            continue
        body, err = _try_call(tok, account_id)
        if body is not None:
            return {"mode": "chatgpt", "raw": body}
        last_err = err
        if not _is_auth_failure(err):
            break

    err_msg = str(last_err) if last_err else "unknown error"
    if last_err is not None and _is_auth_failure(last_err):
        err_msg = (
            f"{err_msg} — tokens may be expired; run `codex login` to refresh"
        )
    return {"mode": "chatgpt", "error": err_msg}


def _is_auth_failure(exc: Exception | None) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (401, 403)
    return False
