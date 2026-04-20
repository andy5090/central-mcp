"""Terminal-aware pane grid math.

`pick_rows(n_panes)` returns the target number of rows for an N-pane
grid, chosen so that each pane ends up roughly pixel-square on the
current terminal. On a wide screen it usually picks 2 rows and lets
columns grow horizontally; on a narrow terminal (SSH from a phone,
split pane, etc) it bumps to 3+ rows so columns don't shrink below
readability.

No runtime cost once the grid is built — this runs exactly once per
session creation, at which point `shutil.get_terminal_size()` reads
the invoking terminal's size. Subsequent terminal resizes don't
retrigger grid recalculation; users who want a different shape
`cmcp down` and re-run.
"""

from __future__ import annotations

import math
import shutil


# Terminal character cells are roughly 2× taller than wide in pixels.
# Converting the char-cell aspect ratio into an effective-pixel ratio
# is the whole point of this constant.
_CHAR_PX_RATIO = 2


def pick_rows(
    n_panes: int,
    *,
    term_size: tuple[int, int] | None = None,
) -> int:
    """Return the target number of grid rows for `n_panes`.

    Heuristic: assuming each char cell is ~2× taller than wide, a
    pane of C columns × R rows is pixel-square when C / (2·R) ≈ 1,
    i.e. C ≈ 2R. Given a terminal of `cols × rows` and an r×c grid
    (c = ceil(n/r)), we have pane_c = cols/c and pane_r = rows/r.
    Solving `pane_c / pane_r = 2` for r gives
    r ≈ sqrt(2 · rows · n / cols).

    Special cases:
      - n ≤ 1: 1 row (nothing to grid).
      - n = 2: side-by-side unless the terminal is narrow (< 60 cols),
        in which case stack vertically.
    """
    if n_panes <= 1:
        return 1
    if term_size is None:
        cols, rows = shutil.get_terminal_size(fallback=(120, 40))
    else:
        cols, rows = term_size
    if n_panes == 2:
        return 2 if cols < 60 else 1

    r_est = math.sqrt(_CHAR_PX_RATIO * rows * n_panes / max(cols, 1))
    return max(1, min(n_panes, round(r_est)))


# Minimum char dimensions below which a pane is no longer useful
# for watching a coding agent at work. Tuned so a 13–15" laptop at
# its native full-screen terminal (≈160–200 cols) lands on exactly
# two column slices — orchestrator on the left, project panes
# vertically stacked on the right. Dropping below 70 cols forces
# file paths, commands and stack traces to hard-wrap; dropping below
# 15 rows shows barely one dispatch before it scrolls off.
_MIN_PANE_COLS = 70
_MIN_PANE_ROWS = 15


def pick_panes_per_window(
    *,
    term_size: tuple[int, int] | None = None,
    min_pane_cols: int = _MIN_PANE_COLS,
    min_pane_rows: int = _MIN_PANE_ROWS,
) -> int:
    """How many panes fit readably in one tmux/zellij tab on the
    current terminal.

    Picks the largest N such that a `rows = pick_rows(N)` grid can fit
    at least `min_pane_cols × min_pane_rows` per pane. In practice the
    answer sits between 2 and ~12 depending on terminal dimensions;
    the caller clamps to `>= 1`.
    """
    if term_size is None:
        import shutil
        cols, rows = shutil.get_terminal_size(fallback=(120, 40))
    else:
        cols, rows = term_size

    if cols < min_pane_cols or rows < min_pane_rows:
        return 1

    # Scan the full candidate range and take the highest n whose grid
    # still clears the readability floor. We can't break on the first
    # failure because pick_rows flips from 1→2 rows somewhere mid-
    # scan, which can widen per-pane cols and let a larger n succeed
    # where a smaller n (in a taller single row) failed.
    #
    # Model: the first tab carries the orchestrator as a full-height
    # left column, so project panes split the remaining width into
    # `top_cols + 1` slots (one of which is orch). Overflow tabs have
    # no orch so they're even roomier — the hub bound keeps both safe.
    best = 1
    for n in range(2, 33):  # hard cap at 32 panes/tab
        r = pick_rows(n, term_size=(cols, rows))
        projects = max(n - 1, 1)
        top_cols = (projects + r - 1) // r
        pane_w = cols // max(top_cols + 1, 1)
        pane_h = rows // max(r, 1)
        if pane_w >= min_pane_cols and pane_h >= min_pane_rows:
            best = n
    return best


def row_sizes(n_panes: int, rows: int) -> list[int]:
    """Distribute `n_panes` across `rows` rows, top-row-heavy when the
    count doesn't divide evenly. Each entry is that row's column count.
    """
    if rows <= 0:
        raise ValueError(f"rows must be >= 1, got {rows}")
    if n_panes <= 0:
        return []
    remaining = n_panes
    out: list[int] = []
    for r_idx in range(rows):
        rows_left = rows - r_idx
        take = (remaining + rows_left - 1) // rows_left  # ceil(remaining / rows_left)
        out.append(take)
        remaining -= take
        if remaining <= 0:
            break
    return out
