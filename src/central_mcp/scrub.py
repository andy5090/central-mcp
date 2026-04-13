"""ANSI escape removal and secret redaction for log output.

Both functions are conservative: default-on for fetch_logs, opt-out with
`scrub_ansi=False` / `scrub_secrets=False`. Regex-based, not perfect —
meant to reduce accidental leakage, not to be a security boundary.
"""

from __future__ import annotations

import re

# Matches CSI, OSC and other common terminal escape sequences.
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

_REDACT = "***REDACTED***"

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9\-_]{20,}"),       # OpenAI / Anthropic
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),            # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),                      # AWS access key id
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),                # Google API key
    re.compile(r"xox[pbaros]-[A-Za-z0-9-]{20,}"),         # Slack tokens
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),         # Generic bearer
]

# Generic key/value patterns on a single line, e.g. `API_KEY=abc123xyz...`
_KV_RE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*)[\"']?([^\s\"'\n]{6,})",
)


def scrub_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def scrub_secrets(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_REDACT, out)
    out = _KV_RE.sub(lambda m: m.group(1) + _REDACT, out)
    return out


def scrub(text: str, *, ansi: bool = True, secrets: bool = True) -> str:
    if ansi:
        text = scrub_ansi(text)
    if secrets:
        text = scrub_secrets(text)
    return text
