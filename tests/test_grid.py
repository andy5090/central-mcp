"""Tests for `central_mcp.grid` — row count + row-size distribution.

pick_rows is the only runtime-sensitive piece; unit tests lock in the
three regimes we care about:
  1. Wide terminals return 2 (today's default, pre-0.6.3 behavior).
  2. Narrow terminals bump to 3+ so pane widths don't collapse.
  3. Tiny pane counts (1, 2) stay at 1 regardless.

row_sizes covers the top-row-heavy split used by the grid builders.
"""

from __future__ import annotations

from central_mcp.grid import pick_rows, row_sizes


class TestPickRows:
    def test_single_pane_always_one_row(self) -> None:
        assert pick_rows(1, term_size=(40, 10)) == 1
        assert pick_rows(1, term_size=(200, 50)) == 1

    def test_two_panes_wide_terminal_stays_single_row(self) -> None:
        # Two panes on a typical laptop / desktop terminal — keep them
        # side-by-side on a single row.
        assert pick_rows(2, term_size=(120, 40)) == 1
        assert pick_rows(2, term_size=(200, 50)) == 1

    def test_two_panes_narrow_terminal_stacks(self) -> None:
        # SSH from a phone / split-view terminal → stack vertically
        # rather than halving the already-tight width.
        assert pick_rows(2, term_size=(40, 30)) == 2

    def test_ten_panes_widescreen_prefers_two_rows(self) -> None:
        # 200x50 is a typical wide-monitor terminal. 10 panes should
        # still collapse to 2 rows × 5 cols, matching the 0.6.2 default.
        assert pick_rows(10, term_size=(200, 50)) == 2

    def test_ten_panes_tall_terminal_bumps_rows(self) -> None:
        # A tall, narrow terminal (more rows than cols in char space)
        # should use more grid rows so each pane gets readable width.
        # 60 cols × 80 rows → ceil-style bump.
        assert pick_rows(10, term_size=(60, 80)) >= 3

    def test_four_panes_square_terminal(self) -> None:
        # A typical "equal aspect" char-cell terminal — 2×2 grid makes
        # sense and pick_rows should recommend it.
        assert pick_rows(4, term_size=(120, 40)) == 2

    def test_rows_never_exceed_pane_count(self) -> None:
        # Edge case: absurdly tall, narrow terminal with 3 panes. Rows
        # should cap at `n_panes` (no empty rows).
        assert pick_rows(3, term_size=(20, 200)) <= 3


class TestPickPanesPerWindow:
    from central_mcp.grid import pick_panes_per_window

    def test_laptop_terminal_caps_reasonably(self) -> None:
        from central_mcp.grid import pick_panes_per_window
        # 120x40 is a typical laptop terminal. Packing more than ~8 panes
        # into it runs each pane below the readability floor.
        n = pick_panes_per_window(term_size=(120, 40))
        assert 2 <= n <= 12

    def test_ultra_wide_terminal_allows_more(self) -> None:
        from central_mcp.grid import pick_panes_per_window
        # A 250x60 terminal can fit more readable panes than 120x40.
        wide = pick_panes_per_window(term_size=(250, 60))
        narrow = pick_panes_per_window(term_size=(120, 40))
        assert wide >= narrow

    def test_tiny_terminal_returns_one(self) -> None:
        from central_mcp.grid import pick_panes_per_window
        # Below the minimum readable floor, one pane fills the window.
        assert pick_panes_per_window(term_size=(30, 10)) == 1
        assert pick_panes_per_window(term_size=(60, 5)) == 1

    def test_min_pane_cols_parameter_respected(self) -> None:
        from central_mcp.grid import pick_panes_per_window
        # Tighter readable width → more panes fit in the same terminal.
        loose = pick_panes_per_window(term_size=(200, 50), min_pane_cols=20)
        strict = pick_panes_per_window(term_size=(200, 50), min_pane_cols=60)
        assert loose > strict


class TestRowSizes:
    def test_even_split(self) -> None:
        assert row_sizes(10, 2) == [5, 5]
        assert row_sizes(9, 3) == [3, 3, 3]
        assert row_sizes(4, 2) == [2, 2]

    def test_top_row_heavy_on_uneven(self) -> None:
        assert row_sizes(5, 2) == [3, 2]
        assert row_sizes(7, 2) == [4, 3]
        assert row_sizes(10, 3) == [4, 3, 3]

    def test_fewer_panes_than_rows(self) -> None:
        # Shouldn't emit empty rows.
        assert row_sizes(2, 3) == [1, 1]

    def test_single_pane_or_row(self) -> None:
        assert row_sizes(1, 1) == [1]
        assert row_sizes(5, 1) == [5]

    def test_zero_panes_empty(self) -> None:
        assert row_sizes(0, 2) == []
