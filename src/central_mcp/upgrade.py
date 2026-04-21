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
# Use the simple index (PEP 691 JSON variant) instead of the legacy
# /pypi/<name>/json endpoint. The simple index propagates new uploads
# within seconds; the JSON API's `info.version` is CDN-cached for
# several minutes and produced "X -> Y available" messages that
# disagreed with what `uv tool install --refresh` actually installed
# (observed 0.8.8 -> 0.8.9 advertised while the install landed on
# the real latest 0.8.10). See 0.8.11 CHANGELOG.
SIMPLE_URL = f"https://pypi.org/simple/{PACKAGE}/"


def installed_version() -> str | None:
    try:
        return version(PACKAGE)
    except PackageNotFoundError:
        return None


def latest_version(timeout: float = 5.0) -> str:
    """Fetch the latest published version from PyPI's simple index.

    Parses the PEP 691 JSON response (`application/vnd.pypi.simple.v1
    +json`) — one entry per distribution file — and returns the
    max version across all non-yanked entries, sorted by the same
    `_parse` tuple comparison used for upgrade decisions below.

    Raises URLError on network / parse failures.
    """
    req = Request(SIMPLE_URL, headers={
        "Accept": "application/vnd.pypi.simple.v1+json",
        "User-Agent": f"{PACKAGE}-cli",
    })
    with urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list) or not files:
        raise URLError("PyPI simple index returned no files")
    versions: set[str] = set()
    prefix = f"{PACKAGE.replace('-', '_')}-"
    for entry in files:
        if not isinstance(entry, dict):
            continue
        if entry.get("yanked"):
            continue
        fn = entry.get("filename")
        if not isinstance(fn, str) or not fn.startswith(prefix):
            continue
        rest = fn[len(prefix):]
        # `<name>-<ver>.tar.gz` or `<name>-<ver>-<tags>.whl`.
        if rest.endswith(".tar.gz"):
            ver = rest[: -len(".tar.gz")]
        else:
            ver = rest.split("-", 1)[0]
        if ver:
            versions.add(ver)
    if not versions:
        raise URLError("PyPI simple index: no parseable versions")
    return max(versions, key=_parse)


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
