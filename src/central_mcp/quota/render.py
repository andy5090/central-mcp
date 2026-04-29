"""Pre-rendered markdown summary for `token_usage` responses.

The orchestrator (LLM) is given a `summary_markdown` field alongside
the raw breakdown so it can surface the result verbatim instead of
re-laying it out as a plain table. The output uses Unicode block bars
(`█`/`░`), emoji color markers (🟢 < 50%, 🟡 50–89%, 🔴 ≥ 90%), and
fixed-width alignment, all inside a fenced code block so monospace
spacing is preserved across markdown renderers.

This keeps formatting consistent across orchestrators (Claude Code,
Codex, opencode, …) — without it each LLM picks its own table style
and the user sees a different view every time.
"""

from __future__ import annotations

from typing import Any

# Color thresholds — applied to subscription-quota bars AND
# project-breakdown bars. Quota: % of cap (clear). Project:
# share-of-total (high concentration is informational, not bad).
_GREEN_MAX = 50.0   # < 50% → 🟢
_YELLOW_MAX = 90.0  # 50–89% → 🟡, ≥ 90% → 🔴

_BAR_WIDTH = 20


def _color_emoji(pct: float) -> str:
    if pct >= _YELLOW_MAX:
        return "🔴"
    if pct >= _GREEN_MAX:
        return "🟡"
    return "🟢"


def _bar(pct: float, width: int = _BAR_WIDTH) -> str:
    p = max(0.0, min(100.0, float(pct)))
    filled = round(p / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _fmt_tokens(n: int) -> str:
    """Compact decimal formatting: 8_972_000 → '8.97M', 260_000 → '260K'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n}"


def _fmt_pct(pct: float) -> str:
    return f"{pct:>3.0f}%"


def _render_quota_section(quota: dict[str, Any]) -> list[str]:
    """Render the SUBSCRIPTION QUOTA block. Returns the list of lines
    (without the section header) or an empty list if nothing useful to
    show.
    """
    out: list[str] = []
    if not quota:
        return out

    # Claude
    claude = quota.get("claude") or {}
    mode = claude.get("mode")
    if mode == "pro":
        err = claude.get("error")
        if err:
            out.append(f"  claude   [Pro]       error: {str(err)[:60]}")
        else:
            for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
                w = claude.get(key) or {}
                if not w:
                    continue
                pct = float(w.get("used_pct") or 0)
                reset = w.get("resets_in") or "?"
                tag = "claude   [Pro]   " if key == "five_hour" else "                 "
                out.append(
                    f"  {tag}  {label}  {_color_emoji(pct)} {_bar(pct)} "
                    f"{_fmt_pct(pct)}  resets {reset}"
                )
    elif mode == "api_key":
        out.append("  claude   [API Key]   no subscription quota")
    elif mode == "error":
        err = claude.get("error") or "unknown"
        out.append(f"  claude   [error]     {str(err)[:60]}")
    elif mode == "not_installed":
        pass  # Don't surface — claude isn't installed.
    elif claude:
        out.append(f"  claude   [{mode}]     no quota info")

    # Codex
    codex = quota.get("codex") or {}
    cmode = codex.get("mode")
    if cmode == "chatgpt":
        err = codex.get("error")
        if err:
            out.append(f"  codex    [chatgpt]   error: {str(err)[:60]}")
        else:
            plan = codex.get("plan") or "chatgpt"
            for key in ("primary", "secondary"):
                w = codex.get(key) or {}
                if not w:
                    continue
                pct = float(w.get("used_pct") or 0)
                reset = w.get("resets_in") or "?"
                window = w.get("window") or "?"
                tag = f"codex    [{plan}]" if key == "primary" else "                 "
                tag = f"{tag:<17}"
                out.append(
                    f"  {tag}  {window}  {_color_emoji(pct)} {_bar(pct)} "
                    f"{_fmt_pct(pct)}  resets {reset}"
                )
    elif cmode == "api_key":
        out.append("  codex    [API Key]   no subscription quota")
    elif cmode == "error":
        err = codex.get("error") or "unknown"
        out.append(f"  codex    [error]     {str(err)[:60]}")
    elif cmode == "not_installed":
        pass

    # Gemini
    gemini = quota.get("gemini") or {}
    gmode = gemini.get("mode")
    if gmode == "auth_only":
        auth = gemini.get("auth_type") or "unknown"
        out.append(f"  gemini   [{auth}]     no quota API available")
    # not_installed → silent.

    return out


def _render_agent_totals_section(
    agent_totals: dict[str, Any] | None,
) -> list[str]:
    """Render the AGENT TOTALS block — per-agent token sums for today
    and the last 7 days. Independent of the caller's `group_by` so this
    section is always available when there's any usage to show.

    Empty/idle agents are dropped (no point listing claude=0 / codex=0
    for users who only ran one agent). Sorted by today desc, week desc
    as tiebreaker, then name.
    """
    out: list[str] = []
    if not agent_totals or not isinstance(agent_totals, dict):
        return out
    if "error" in agent_totals:
        return out

    rows: list[tuple[str, int, int]] = []
    for name, slice_ in agent_totals.items():
        if not isinstance(slice_, dict):
            continue
        today = int(slice_.get("today") or 0)
        week = int(slice_.get("week") or 0)
        if today == 0 and week == 0:
            continue
        rows.append((name, today, week))
    if not rows:
        return out

    rows.sort(key=lambda r: (-r[1], -r[2], r[0]))

    name_width = max(len(r[0]) for r in rows)
    today_strs = [_fmt_tokens(r[1]) for r in rows]
    week_strs = [_fmt_tokens(r[2]) for r in rows]
    today_width = max(len(s) for s in today_strs)
    week_width = max(len(s) for s in week_strs)

    out.append("AGENT TOTALS")
    for (name, _today, _week), today_s, week_s in zip(rows, today_strs, week_strs):
        out.append(
            f"  {name.ljust(name_width)}  "
            f"today {today_s.rjust(today_width)}   ·   "
            f"7d {week_s.rjust(week_width)}"
        )
    return out


def _render_breakdown_section(
    breakdown: dict[str, dict[str, Any]],
    total: dict[str, Any],
    period: str,
) -> list[str]:
    """Render the PROJECT BREAKDOWN block. Returns header line + body
    lines, or empty list when there's no usage to show.
    """
    out: list[str] = []
    if not breakdown:
        return out

    grand_total = int((total or {}).get("total") or 0)
    if grand_total <= 0:
        return out

    # Compute share-of-total per row, preserve breakdown's existing
    # iteration order (ORCHESTRATOR is pinned first by the aggregator).
    rows: list[tuple[str, int, float]] = []
    name_width = 0
    for name, entry in breakdown.items():
        tokens = int((entry or {}).get("total") or 0)
        if tokens <= 0:
            continue
        share = tokens / grand_total * 100
        rows.append((name, tokens, share))
        name_width = max(name_width, len(name))
    if not rows:
        return out

    name_width = min(name_width, 24)

    out.append(
        f"PROJECT BREAKDOWN ({period}: {_fmt_tokens(grand_total)} tokens)"
    )
    for name, tokens, share in rows:
        display_name = name if len(name) <= name_width else name[: name_width - 1] + "…"
        out.append(
            f"  {display_name.ljust(name_width)}  "
            f"{_color_emoji(share)} {_bar(share)}  "
            f"{_fmt_tokens(tokens):>8}  {_fmt_pct(share)}"
        )
    return out


def render_summary(result: dict[str, Any]) -> str:
    """Render the `token_usage` result as a fenced-markdown summary
    block. The orchestrator can paste this verbatim into its reply
    instead of re-formatting the raw `breakdown` / `quota` payload.

    Output shape:
      ```
      **Token Usage — today (Asia/Seoul)**

      ```text
      SUBSCRIPTION QUOTA
        claude   [Pro]      5h  🟢 ████░░░░░░░░░░░░░░░░  20%  resets 2h31m
        ...

      PROJECT BREAKDOWN (today: 73.4M tokens)
        ORCHESTRATOR        🟢 ████░░░░░░░░░░░░░░░░  8.97M  12%
        tui-4-everything    🟡 ██████████████░░░░░░  53.6M  73%
        ...
      ```
      ```
    """
    period = result.get("period", "today")
    tz = result.get("timezone", "")
    breakdown = result.get("breakdown") or {}
    total = result.get("total") or {}
    quota = result.get("quota") or {}
    agent_totals = result.get("agent_totals") or {}

    lines: list[str] = []
    title_suffix = f" ({tz})" if tz else ""
    lines.append(f"**Token Usage — {period}{title_suffix}**")
    lines.append("")
    lines.append("```text")

    quota_lines = _render_quota_section(quota)
    if quota_lines:
        lines.append("SUBSCRIPTION QUOTA")
        lines.extend(quota_lines)

    agent_lines = _render_agent_totals_section(agent_totals)
    if agent_lines:
        if quota_lines:
            lines.append("")
        lines.extend(agent_lines)

    breakdown_lines = _render_breakdown_section(breakdown, total, period)
    if breakdown_lines:
        if quota_lines or agent_lines:
            lines.append("")
        lines.extend(breakdown_lines)

    if not quota_lines and not agent_lines and not breakdown_lines:
        lines.append("(no data for this period)")

    lines.append("```")
    return "\n".join(lines)
