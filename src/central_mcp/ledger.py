"""The status ledger — durable per-project *intent*.

`pulse` answers "what is true right now" by reading the repository, and
recomputes it on every call. This module holds the other half: what
somebody *meant* — what was done, what was left, what comes next — which
no amount of reading git can produce. A commit is evidence, never
intent, and the highest-value knowledge (an approach tried and rejected)
leaves no commit at all.

The two halves stay deliberately separate:

  * pulse is ground truth and is never stored.
  * the ledger is claims, is stored, and is always attributed.

Every entry carries a `source` so a reader can tell who is talking:

  ``agent``  an agent recorded this at the end of its own work
  ``user``   a human wrote it (``cmcp note``, or answering a briefing)

Those are the only two, and the omissions are load-bearing.

There is no ``inferred`` source: synthesizing entries from commit history
would make "the agent said this" and "the hub guessed this"
indistinguishable, and the ledger's whole value is that you can trust
what it says. Gaps are computed at read time by `pulse` instead, so a gap
can never go stale.

There is no ``dispatch`` source either — no stub for a dispatch that
failed or recorded nothing. Such a stub would add nothing `pulse` doesn't
already report, and because *any* entry advances the watermark it would
silence the drift signal for work that genuinely went unrecorded. Silence
is the correct output when nobody said anything.

The file is plain markdown at `~/.central-mcp/projects/<name>/STATUS.md`,
append-only, newest at the bottom, and meant to be hand-editable — the
parser is liberal about spacing, separators and unknown sources so that
editing it by hand can't corrupt it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from central_mcp import paths

#: Sources central-mcp itself will write. A hand-edited file may carry
#: anything; `read` preserves unknown sources rather than dropping the entry.
SOURCES = ("agent", "user")

#: `## <timestamp> · <source>` — liberal about the separator and tolerant
#: of a missing source, because humans edit this file.
_HEADING_RE = re.compile(
    r"^##\s+(?P<ts>\S+)(?:\s*[·\-—]\s*(?P<source>[A-Za-z][\w-]*))?\s*$"
)

_NEXT_RE = re.compile(r"^\s*next\s*:\s*(?P<body>.+?)\s*$", re.IGNORECASE)

_HEADER = """# Status — {project}

<!-- Status ledger. Append-only, newest at the bottom; edit it by hand freely.

     central-mcp reads any section shaped `## <ISO timestamp> · <source>`.
     The body is free text. A line beginning with `Next:` is picked up as
     the project's next step and is what a return briefing will offer back
     to you for confirmation.

     Sources: agent (an agent recorded its own work) · user (you).
     Nothing here is ever inferred from git — see `ledger.py`. -->
"""


@dataclass(frozen=True)
class Entry:
    """One ledger section.

    `ts` is None for a hand-written heading whose timestamp doesn't
    parse — the entry is still returned (losing user-written content is
    worse than a missing sort key), it just can't anchor the watermark.
    """

    ts: str | None
    source: str
    body: str
    next_step: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "source": self.source,
            "body": self.body,
            "next_step": self.next_step,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def path_for(project_name: str) -> Path:
    """Where `project_name`'s ledger lives (whether or not it exists yet)."""
    return paths.project_status_path(project_name)


def exists(project_name: str) -> bool:
    return path_for(project_name).is_file()


def _escape_body(body: str) -> str:
    """Neutralize markdown headings inside a body so they can't be misread
    as the start of a new entry. Backslash-escaping keeps the text visually
    identical when rendered.
    """
    return "\n".join(
        ("\\" + line if line.lstrip().startswith("#") else line)
        for line in body.splitlines()
    )


def append(
    project_name: str,
    body: str,
    *,
    source: str = "user",
    next_step: str | None = None,
    ts: str | None = None,
) -> Entry:
    """Append one entry and return it.

    Creates the file (with its explanatory header) on first write.
    `next_step`, when given, is appended as a `Next:` line — callers that
    already have one embedded in `body` can leave it out.
    """
    if source not in SOURCES:
        raise ValueError(
            f"source must be one of {', '.join(SOURCES)}; got {source!r}"
        )
    text = (body or "").strip()
    if not text and not (next_step or "").strip():
        raise ValueError("refusing to append an empty ledger entry")

    stamp = ts or _now_iso()
    lines = [_escape_body(text)] if text else []
    if next_step and next_step.strip():
        lines.append(f"Next: {next_step.strip()}")
    section = f"\n## {stamp} · {source}\n" + "\n".join(lines) + "\n"

    path = path_for(project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_HEADER.format(project=project_name), encoding="utf-8")
    # Single append write — concurrent dispatch completions interleave
    # entries rather than corrupting each other.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(section)

    return _entry_from(stamp, source, "\n".join(lines))


def _entry_from(ts: str, source: str, raw_body: str) -> Entry:
    next_step: str | None = None
    kept: list[str] = []
    for line in raw_body.splitlines():
        m = _NEXT_RE.match(line)
        if m:
            # Last Next: wins — a later line is a correction of an earlier one.
            next_step = m.group("body")
        else:
            kept.append(line)
    parsed_ts = _parse_ts(ts)
    return Entry(
        ts=ts if parsed_ts else None,
        source=source,
        body="\n".join(kept).strip(),
        next_step=next_step,
    )


def read(project_name: str, *, limit: int | None = None) -> list[Entry]:
    """Entries newest-first. Missing or unreadable file reads as empty —
    an absent ledger is an ordinary state, not an error.
    """
    path = path_for(project_name)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    entries: list[Entry] = []
    ts: str | None = None
    source = "user"
    buf: list[str] = []

    def flush() -> None:
        if ts is not None:
            entries.append(_entry_from(ts, source, "\n".join(buf)))

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            ts = m.group("ts")
            # A hand-written heading with no source is somebody typing
            # into the file, which is exactly what `user` means.
            source = m.group("source") or "user"
            buf = []
        elif ts is not None:
            buf.append(line)
    flush()

    entries.reverse()
    return entries[:limit] if limit else entries


def watermark(project_name: str) -> str | None:
    """Timestamp of the newest entry — "the ledger covers up to here".

    `pulse` compares this against real activity to decide whether the
    ledger has fallen behind the project. Entries whose timestamp didn't
    parse are skipped: they can't bound a range.
    """
    best: datetime | None = None
    best_raw: str | None = None
    for e in read(project_name):
        if not e.ts:
            continue
        dt = _parse_ts(e.ts)
        if dt and (best is None or dt > best):
            best, best_raw = dt, e.ts
    return best_raw


def next_step(project_name: str) -> Entry | None:
    """The newest entry that names a next step, or None.

    Returned as the whole entry rather than a bare string so a briefing
    can say *when* and *who* — "you said this three days ago" is what
    makes a stale plan visible as stale.
    """
    for e in read(project_name):
        if e.next_step:
            return e
    return None
