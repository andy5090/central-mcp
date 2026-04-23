"""Detect Gemini auth type.

Gemini provides no programmatic quota API — neither response headers nor a
dedicated endpoint expose remaining quota. This module returns auth type info
so the monitor can display appropriate messaging.
Returns None when Gemini CLI is not installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _settings_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def fetch() -> dict[str, Any] | None:
    """Return Gemini auth type, or None if Gemini is not installed.

    Possible shapes:
      None                              — Gemini CLI not installed
      {"auth_type": "gemini-api-key"}  — Google AI Studio API key
      {"auth_type": "oauth-personal"}  — Google personal OAuth
      {"auth_type": "unknown"}         — settings unreadable
    """
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        return {"auth_type": data.get("selectedAuthType", "unknown")}
    except FileNotFoundError:
        return None
    except Exception:
        return {"auth_type": "unknown"}
