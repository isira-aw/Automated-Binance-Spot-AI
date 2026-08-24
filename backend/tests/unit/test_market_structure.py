"""Market structure engine correctness (§20)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.engines.market_structure import (
    SwingKind,
    Trend,
    compute_all,
    find_swing_points,
)


def zigzag_ohlcv(prices: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV frame from a list of closing prices, with
    high/low tight around close so swing detection is driven by the shape of
    ``prices`` alone."""
    close = pd.Series(prices, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": pd.Series([100.0] * len(prices)),
        }
    )


class TestSwingPoints:
    def test_a_single_peak_is_detected_as_a_swing_high(self):
        # window=3: need 3 bars rising into the peak and 3 falling away.
        prices = [1, 2, 3, 10, 3, 2, 1]
        df = zigzag_ohlcv(prices)
        swings = find_swing_points(df["high"], df["low"], window=3)
        highs = [s for s in swings if s.kind is SwingKind.HIGH]
        assert len(highs) == 1
        assert highs[0].index == 3
        assert highs[0].confirmed_index == 6
        assert highs[0].price == pytest.approx(10.1)

    def test_a_single_trough_is_detected_as_a_swing_low(self):
        prices = [10, 9, 8, 1, 8, 9, 10]
        df = zigzag_ohlcv(prices)
        swings = find_swing_points(df["high"], df["low"], window=3)
        lows = [s for s in swings if s.kind is SwingKind.LOW]
        assert len(lows) == 1
        assert lows[0].index == 3

    def test_a_monotonic_series_has_no_swings(self):
        df = zigzag_ohlcv(list(range(1, 20)))
        swings = find_swing_points(df["high"], df["low"], window=3)
        assert swings == []

    def test_a_tie_at_the_extreme_is_not_treated_as_a_confirmed_swing(self):
        """Two equal peaks in the same window are ambiguous -- neither one is
        confirmed as *the* swing high, rather than arbitrarily picking one."""
        prices = [1, 2, 5, 3, 5, 2, 1]
        df = zigzag_ohlcv(prices)
        swings = find_swing_points(df["high"], df["low"], window=3)
        highs = [s for s in swings if s.kind is SwingKind.HIGH]
        assert highs == []


class TestStructureSequence:
    """window=1 so each extremum only competes with its immediate neighbours
    -- verified directly against the implementation before being pinned here,
    since hand-predicting a fractal window's ties is error-prone."""

    def test_ascending_peaks_and_troughs_are_higher_highs_and_higher_lows(self):
        prices = [3, 6, 3, 4, 8, 4, 5, 9, 5, 6, 10, 6]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["is_higher_high"].any()
        assert result["is_higher_low"].any()
        assert not result["is_lower_high"].any()
        assert not result["is_lower_low"].any()

    def test_descending_peaks_and_troughs_are_lower_highs_and_lower_lows(self):
        prices = [8, 5, 8, 7, 3, 7, 6, 2, 6, 5, 1, 5]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["is_lower_high"].any()
        assert result["is_lower_low"].any()
        assert not result["is_higher_high"].any()
        assert not result["is_higher_low"].any()

    def test_trend_turns_bullish_after_a_higher_high(self):
        prices = [3, 6, 3, 4, 8, 4, 5, 9, 5, 6, 10, 6]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["structure_trend"].iloc[-1] == Trend.BULLISH.value

    def test_change_of_character_marks_a_trend_reversal(self):
        # Bullish sequence (rising peaks/troughs) then a break to the downside.
        prices = [3, 6, 3, 4, 8, 4, 5, 9, 5, 6, 10, 6, 0.5, 3, 0.5]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["change_of_character"].any()


class TestBreakoutBreakdown:
    def test_a_close_above_resistance_is_a_breakout(self):
        prices = [3, 6, 3, 4, 20]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["breakout"].any()

    def test_a_close_below_support_is_a_breakdown(self):
        prices = [8, 5, 8, 7, -5]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["breakdown"].any()

    def test_a_breakout_that_reverts_is_flagged_false_within_the_window(self):
        # Break above resistance, then close back below it within the
        # confirmation window (FALSE_BREAKOUT_WINDOW).
        prices = [3, 6, 3, 4, 20, 1, 1, 1]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["breakout"].any()
        assert result["false_breakout"].any()

    def test_a_breakout_that_holds_is_never_flagged_false(self):
        prices = [3, 6, 3, 4, 20, 21, 22, 23, 24, 25]
        df = zigzag_ohlcv(prices)
        result = compute_all(df, window=1)
        assert result["breakout"].any()
        assert not result["false_breakout"].any()


class TestNoLookahead:
    """The same truncated-prefix method as the indicator module's leakage
    tests: every value at bar i in a truncated computation must match the
    same bar's value in the full computation.  For this module the risk is
    subtler than a centred window -- a confirmation delay is legitimate, but
    only if every field is attributed to its confirmation bar, never to the
    bar the underlying swing/break actually occurred at.
    """

    @pytest.fixture
    def ohlcv(self) -> pd.DataFrame:
        rng = np.random.default_rng(11)
        n = 200
        close = 100 + np.cumsum(rng.normal(0, 1.5, n))
        return pd.DataFrame(
            {
                "open": close,
                "high": close + rng.uniform(0, 1, n),
                "low": close - rng.uniform(0, 1, n),
                "close": close,
                "volume": rng.uniform(10, 100, n),
            }
        )

    def test_every_field_matches_the_full_computation_up_to_the_cut(self, ohlcv):
        cut = 150
        full = compute_all(ohlcv, window=5)
        truncated = compute_all(ohlcv.iloc[:cut], window=5)
        for column in full.columns:
            pd.testing.assert_series_equal(
                full[column].iloc[:cut].reset_index(drop=True),
                truncated[column].reset_index(drop=True),
                check_names=False,
            )

    def test_a_deliberately_leaky_confirmation_index_would_be_caught(self):
        """Negative control, built deterministically rather than relying on a
        random series to happen to contain the right shape.

        A single sharp peak at index 7 needs bars up to index 10
        (index + window) to be confirmed.  With only 9 bars available (cut=9),
        the truncated computation cannot see far enough past the peak to
        confirm it at all -- but a version that (incorrectly) attributed the
        swing to its own bar rather than its confirmation bar would already
        "know" about it in the full computation's first 9 bars, producing a
        mismatch against the truncated computation.  If this test does not
        raise, the prefix-invariant check above is not actually exercising the
        attribution-timing risk this module is built around.
        """
        prices = [1, 2, 3, 4, 5, 6, 7, 20, 7, 6, 5, 4, 3, 2, 1]
        close = pd.Series(prices, dtype=float)
        high, low = close + 0.1, close - 0.1

        from app.engines.market_structure import find_swing_points

        cut = 9
        full_swings = find_swing_points(high, low, window=3)
        truncated_swings = find_swing_points(high.iloc[:cut], low.iloc[:cut], window=3)
        assert any(s.index == 7 for s in full_swings)
        assert not any(s.index == 7 for s in truncated_swings)  # not yet confirmable

        def leaky_series(swings, length):
            values = [None] * length
            for swing in swings:
                values[swing.index] = swing.price  # leak: attributed too early
            return pd.Series(values)

        full_leaky = leaky_series(full_swings, len(prices))
        truncated_leaky = leaky_series(truncated_swings, cut)
        with pytest.raises(AssertionError):
            pd.testing.assert_series_equal(
                full_leaky.iloc[:cut].reset_index(drop=True),
                truncated_leaky.reset_index(drop=True),
                check_names=False,
            )
