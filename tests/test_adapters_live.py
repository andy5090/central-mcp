"""Live-CLI contract tests — actually shell out to each agent binary.

These tests catch the class of bug our unit tests cannot: the argv we
emit looks syntactically fine but the real CLI rejects it (flag renamed,
flag doesn't exist, flag takes a value we didn't provide, etc.).

Default `pytest` does NOT run these — they require each agent binary to
be on PATH. Opt in with:

    pytest -m live                    # run only live tests
    pytest -m "not live" or default   # skip them (this is CI default)

Each parametrized case skips cleanly when the binary is absent, so a
machine with only `claude` installed still yields useful signal.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from central_mcp.adapters.base import get_adapter

pytestmark = pytest.mark.live

AGENTS_UNDER_TEST = ["claude", "codex", "gemini", "droid", "opencode"]


def _run_help(argv: list[str]) -> str:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
    return (result.stdout or "") + "\n" + (result.stderr or "")


def _help_text_for_argv(binary: str, argv: list[str]) -> str:
    """Concatenate top-level help AND — if argv[1] is a subcommand like
    `exec` — the subcommand help too, since flags like
    `--skip-permissions-unsafe` are only documented under the
    subcommand level (e.g. `droid exec --help` but not `droid --help`).
    """
    pages = [_run_help([binary, "--help"])]
    # Only treat argv[1] as a subcommand if it's a bare word (no dashes)
    # and non-empty. For claude/gemini there's no subcommand.
    if len(argv) >= 2 and argv[1] and not argv[1].startswith("-"):
        subcmd = argv[1]
        pages.append(_run_help([binary, subcmd, "--help"]))
    return "\n".join(pages)


_VALUE_MARKER = re.compile(
    # <something>   or   [lowercase-word]   or   =VALUE
    # Strictly a value placeholder, not description text.
    r"(?:<[^>]+>|\[[a-z][\w\-]*\]|=\S+)"
)


def _flag_looks_value_taking(help_text: str, flag: str) -> bool:
    """True if help text shows `flag` as accepting a value.

    Strategy: find lines that mention the flag, then check for a value
    marker immediately following it (possibly after a comma-separated
    alias). Uses strict markers — `<value>`, `[value]`, `=VALUE` — to
    avoid matching description text that happens to start with a
    capitalized word.
    """
    esc = re.escape(flag)
    flag_boundary = rf"(?<![A-Za-z0-9_\-]){esc}(?![A-Za-z0-9_\-])"
    for line in help_text.splitlines():
        if not re.search(flag_boundary, line):
            continue
        idx = re.search(flag_boundary, line).end()
        # Accept an optional alias form `, --longform` after the flag,
        # then look for a value marker.
        tail = line[idx:]
        alias_consumed = re.match(r"(?:,\s*-\S+)?", tail)
        if alias_consumed:
            tail = tail[alias_consumed.end():]
        m = re.match(r"\s+", tail)
        if not m:
            continue
        after_ws = tail[m.end():]
        marker = _VALUE_MARKER.match(after_ws)
        if marker:
            return True
    return False


def _skip_if_missing(binary: str) -> None:
    if shutil.which(binary) is None:
        pytest.skip(f"{binary} binary not installed on PATH")


@pytest.mark.parametrize("agent", AGENTS_UNDER_TEST)
def test_help_contains_our_flags(agent: str) -> None:
    """Every flag our adapter emits with resume+bypass must appear in
    `<binary> --help` (or `<binary> <subcmd> --help`). Catches: flag
    renamed or removed; adapter typos; or an entirely fictional flag
    (a historical bug: the amp adapter shipped with `--no-confirm`,
    which never existed — the correct flag was `--dangerously-allow-all`)."""
    _skip_if_missing(agent)
    argv = get_adapter(agent).exec_argv("probe", resume=True, bypass=True)
    assert argv is not None
    help_text = _help_text_for_argv(agent, argv)
    missing = []
    for tok in argv[1:]:
        if tok.startswith("-") and tok not in help_text:
            missing.append(tok)
    assert not missing, (
        f"{agent}: adapter emits flags not found in help text for "
        f"{agent!r} (top-level or subcommand): {missing}. "
        f"Check the adapter against the current CLI."
    )


@pytest.mark.parametrize("agent", AGENTS_UNDER_TEST)
def test_no_boolean_flag_is_actually_value_taking(agent: str) -> None:
    """For every flag we emit *without a following value*, the CLI's
    help must NOT document it as value-taking. This is the class of
    bug that bit us on droid: `-r` was emitted as a boolean, but
    `droid exec`'s help shows `-r, --reasoning-effort <level>` — so
    droid silently ate the next flag as `-r`'s argument and errored."""
    _skip_if_missing(agent)
    argv = get_adapter(agent).exec_argv("probe", resume=True, bypass=True)
    assert argv is not None
    help_text = _help_text_for_argv(agent, argv)

    emitted_as_boolean: list[str] = []
    for i, tok in enumerate(argv):
        if not tok.startswith("-"):
            continue
        next_tok = argv[i + 1] if i + 1 < len(argv) else None
        if next_tok is None or next_tok.startswith("-"):
            emitted_as_boolean.append(tok)

    offenders: list[str] = []
    for flag in emitted_as_boolean:
        if _flag_looks_value_taking(help_text, flag):
            offenders.append(flag)
    assert not offenders, (
        f"{agent}: these flags are emitted as booleans but the CLI's "
        f"help documents them as value-taking — the CLI will swallow "
        f"the next token as their argument: {offenders}"
    )


@pytest.mark.parametrize("agent", AGENTS_UNDER_TEST)
def test_binary_help_exits_cleanly(agent: str) -> None:
    """Sanity: `<binary> --help` must produce non-empty output."""
    _skip_if_missing(agent)
    assert _run_help([agent, "--help"]).strip(), f"{agent} --help produced no output"
