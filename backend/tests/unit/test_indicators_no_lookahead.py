"""§18: no indicator may use information from a future candle.

The proof used here is standard for this kind of check: computing the same
indicator on a truncated prefix of a series must reproduce the same values as
the corresponding prefix of the full-series computation.  If any indicator
used a centred window, a forward shift, or global statistics, truncating the
series would change earlier values too and this test would catch it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.technical import indicators as ta


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 300
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0, 1, n),
            "low": close - rng.uniform(0, 1, n),
            "close": close,
            "volume": rng.uniform(10, 100, n),
        }
    )


def assert_prefix_invariant(full_result: pd.Series, truncated_result: pd.Series) -> None:
    """Every value in the truncated computation must equal the corresponding
    value from the full computation -- nothing after the truncation point may
    have influenced it."""
    aligned = full_result.iloc[: len(truncated_result)]
    pd.testing.assert_series_equal(
        aligned.reset_index(drop=True),
        truncated_result.reset_index(drop=True),
        check_names=False,
    )


CUT = 200


@pytest.mark.parametrize(
    "name,builder",
    [
        ("sma", lambda df: ta.sma(df["close"], 20)),
        ("ema", lambda df: ta.ema(df["close"], 12)),
        ("wma", lambda df: ta.wma(df["close"], 20)),
        (
            "rolling_vwap",
            lambda df: ta.rolling_vwap(df["high"], df["low"], df["close"], df["volume"], 20),
        ),
        ("rsi", lambda df: ta.rsi(df["close"], 14)),
        ("roc", lambda df: ta.roc(df["close"], 12)),
        ("cci", lambda df: ta.cci(df["high"], df["low"], df["close"], 20)),
        ("williams_r", lambda df: ta.williams_r(df["high"], df["low"], df["close"], 14)),
        ("atr", lambda df: ta.atr(df["high"], df["low"], df["close"], 14)),
        ("realized_volatility", lambda df: ta.realized_volatility(df["close"], 20)),
        ("obv", lambda df: ta.obv(df["close"], df["volume"])),
        ("volume_zscore", lambda df: ta.volume_zscore(df["volume"], 20)),
    ],
)
def test_series_indicator_has_no_lookahead(ohlcv, name, builder):
    full = builder(ohlcv)
    truncated = builder(ohlcv.iloc[:CUT])
    assert_prefix_invariant(full, truncated)


@pytest.mark.parametrize(
    "name,builder",
    [
        (
            "directional_movement",
            lambda df: ta.directional_movement(df["high"], df["low"], df["close"], 14),
        ),
        ("macd", lambda df: ta.macd(df["close"])),
        ("stochastic", lambda df: ta.stochastic(df["high"], df["low"], df["close"])),
        ("bollinger_bands", lambda df: ta.bollinger_bands(df["close"])),
    ],
)
def test_dataframe_indicator_has_no_lookahead(ohlcv, name, builder):
    full = builder(ohlcv)
    truncated = builder(ohlcv.iloc[:CUT])
    for column in full.columns:
        assert_prefix_invariant(full[column], truncated[column])


def test_volatility_percentile_has_no_lookahead(ohlcv):
    full_atr = ta.atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14)
    full = ta.volatility_percentile(full_atr, 100)
    truncated_atr = ta.atr(
        ohlcv["high"].iloc[:CUT], ohlcv["low"].iloc[:CUT], ohlcv["close"].iloc[:CUT], 14
    )
    truncated = ta.volatility_percentile(truncated_atr, 100)
    assert_prefix_invariant(full, truncated)


def test_price_volume_correlation_has_no_lookahead(ohlcv):
    full = ta.price_volume_correlation(ohlcv["close"], ohlcv["volume"], 20)
    truncated = ta.price_volume_correlation(
        ohlcv["close"].iloc[:CUT], ohlcv["volume"].iloc[:CUT], 20
    )
    assert_prefix_invariant(full, truncated)


def test_compute_all_has_no_lookahead(ohlcv):
    full = ta.compute_all(ohlcv)
    truncated = ta.compute_all(ohlcv.iloc[:CUT])
    for column in full.columns:
        assert_prefix_invariant(full[column], truncated[column])


def test_a_deliberately_centred_window_would_be_caught():
    """Negative control: proves the prefix-invariant check actually detects a
    lookahead violation, rather than passing everything by construction."""
    close = pd.Series(np.arange(50, dtype=float))
    leaky = close.rolling(window=5, center=True).mean()  # uses future rows
    truncated_leaky = close.iloc[:30].rolling(window=5, center=True).mean()
    with pytest.raises(AssertionError):
        assert_prefix_invariant(leaky, truncated_leaky)
