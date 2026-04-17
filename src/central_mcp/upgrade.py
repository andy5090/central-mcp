"""`central-mcp upgrade` — self-update by querying PyPI.

Hides the `uv tool install --reinstall --refresh central-mcp`
incantation behind a friendlier CLI. Falls back to `pip install
--upgrade` when `uv` isn't on PATH so pip-installed users aren't
stranded. Network and install failures return non-zero exit codes;
the CLI layer prints human-readable errors.

No new runtime dependency — version lookup uses `urllib.request` and
`json` from the stdlib, which is fine for a one-shot query.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from urllib.error import URLError
from urllib.request import Request, urlopen

PACKAGE = "central-mcp"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE}/json"


def installed_version() -> str | None:
    try:
        return version(PACKAGE)
    except PackageNotFoundError:
        return None


def latest_version(timeout: float = 5.0) -> str:
    """Fetch the latest published version from PyPI.

    Raises URLError on network failures or bad JSON; caller formats
    the message for the user.
    """
    req = Request(PYPI_URL, headers={
        "Accept": "application/json",
        "User-Agent": f"{PACKAGE}-cli",
    })
    with urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    v = data.get("info", {}).get("version")
    if not v:
        raise URLError("PyPI response missing info.version")
    return v


def _parse(v: str) -> tuple[int, ...]:
    """Best-effort numeric tuple for comparison ('0.2.0' > '0.1.10').

    Pre-release tags and other suffixes are dropped — we only call
    this to decide upgrade vs. no-op, and anything non-numeric in the
    tail means "different release, install it".
    """
    parts = []
    for chunk in v.split("."):
        # Strip the first non-digit tail (e.g. '1a2' → '1').
        num = ""
        for c in chunk:
            if c.isdigit():
                num += c
            else:
                break
        if num:
            parts.append(int(num))
        else:
            return tuple(parts)
    return tuple(parts)


def _upgrade_command() -> list[str]:
    if shutil.which("uv"):
        return ["uv", "tool", "install", "--reinstall", "--refresh", PACKAGE]
    return [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE]


def run(check_only: bool = False) -> int:
    cur = installed_version()
    if cur is None:
        print(f"{PACKAGE} is not installed in this environment", file=sys.stderr)
        return 1

    try:
        latest = latest_version()
    except URLError as e:
        print(f"could not reach PyPI: {e}", file=sys.stderr)
        return 1

    if _parse(cur) >= _parse(latest):
        print(f"{PACKAGE} {cur} is up to date")
        return 0

    print(f"{PACKAGE}: {cur} → {latest} available")
    if check_only:
        print("(--check only; run without --check to upgrade)")
        return 0

    cmd = _upgrade_command()
    print(f"running: {' '.join(cmd)}")
    return subprocess.call(cmd)
