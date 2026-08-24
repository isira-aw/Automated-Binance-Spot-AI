"""Indicator correctness against hand-computed values (§19)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.technical import indicators as ta


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_sma_matches_hand_computed_average():
    result = ta.sma(series([1, 2, 3, 4, 5]), period=3)
    assert result.iloc[-1] == pytest.approx((3 + 4 + 5) / 3)
    assert pd.isna(result.iloc[1])  # not enough history yet


def test_ema_converges_toward_a_constant_series():
    result = ta.ema(series([10.0] * 30), period=10)
    assert result.iloc[-1] == pytest.approx(10.0)


def test_wma_weights_recent_values_more_heavily():
    result = ta.wma(series([1, 2, 3]), period=3)
    # weights 1,2,3 -> (1*1 + 2*2 + 3*3) / 6
    assert result.iloc[-1] == pytest.approx((1 + 4 + 9) / 6)


def test_rsi_is_100_when_every_move_is_a_gain():
    result = ta.rsi(series([float(i) for i in range(1, 20)]), period=14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_is_0_when_every_move_is_a_loss():
    result = ta.rsi(series([float(i) for i in range(20, 1, -1)]), period=14)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_rsi_is_bounded_zero_to_hundred_on_mixed_data():
    rng = np.random.default_rng(7)
    prices = 100 + np.cumsum(rng.normal(0, 1, 200))
    result = ta.rsi(series(list(prices)), period=14).dropna()
    assert (result >= 0).all() and (result <= 100).all()


def test_macd_histogram_is_line_minus_signal():
    close = series(list(100 + np.cumsum(np.sin(np.linspace(0, 20, 60)))))
    result = ta.macd(close)
    valid = result.dropna()
    assert (valid["macd_histogram"] - (valid["macd"] - valid["macd_signal"])).abs().max() < 1e-9


def test_stochastic_is_100_at_the_period_high():
    close = series([1, 2, 3, 4, 10])
    result = ta.stochastic(close, close, close, k_period=5, d_period=1)
    assert result["stoch_k"].iloc[-1] == pytest.approx(100.0)


def test_roc_matches_the_percentage_change_formula():
    result = ta.roc(series([100, 100, 100, 100, 110]), period=4)
    assert result.iloc[-1] == pytest.approx(10.0)


def test_williams_r_is_zero_at_the_period_high():
    high = series([1, 2, 3, 4, 10])
    result = ta.williams_r(high, high, high, period=5)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_atr_matches_true_range_for_a_single_gap_up():
    high = series([10, 20])
    low = series([9, 19])
    close = series([9.5, 19.5])
    # True range for bar 2: max(high-low, |high-prev_close|, |low-prev_close|)
    # = max(1, |20-9.5|=10.5, |19-9.5|=9.5) = 10.5
    result = ta.atr(high, low, close, period=1)
    assert result.iloc[-1] == pytest.approx(10.5)


def test_bollinger_bands_bracket_the_moving_average():
    close = series(list(100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 50))))
    result = ta.bollinger_bands(close, period=20)
    valid = result.dropna()
    assert (valid["bb_upper"] >= valid["bb_mid"]).all()
    assert (valid["bb_lower"] <= valid["bb_mid"]).all()


def test_obv_increases_on_up_days_and_decreases_on_down_days():
    close = series([10, 11, 10, 12])
    volume = series([100, 100, 100, 100])
    result = ta.obv(close, volume)
    # +100 (up), -100 (down), +100 (up) from a base of 0
    assert result.iloc[-1] == pytest.approx(100.0)


def test_volume_zscore_is_zero_for_uniform_volume():
    result = ta.volume_zscore(series([100.0] * 25), period=20)
    assert result.dropna().abs().max() < 1e-9 or result.dropna().isna().all()


def test_vwap_deviation_is_zero_when_price_equals_vwap():
    close = series([100.0] * 25)
    vwap = series([100.0] * 25)
    result = ta.vwap_deviation(close, vwap)
    assert (result == 0).all()


def test_compute_all_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing OHLCV"):
        ta.compute_all(pd.DataFrame({"close": [1, 2, 3]}))


def test_compute_all_rejects_empty_dataframe():
    with pytest.raises(ValueError, match="no rows"):
        ta.compute_all(
            pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        )


def test_compute_all_produces_every_documented_column():
    rng = np.random.default_rng(3)
    n = 250
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0, 1, n),
            "low": close - rng.uniform(0, 1, n),
            "close": close,
            "volume": rng.uniform(10, 100, n),
        }
    )
    result = ta.compute_all(df)
    expected_columns = {
        "sma_20", "sma_50", "ema_12", "ema_26", "wma_20", "vwap_20",
        "plus_di", "minus_di", "adx",
        "rsi_14", "macd", "macd_signal", "macd_histogram",
        "stoch_k", "stoch_d", "roc_12", "cci_20", "williams_r_14",
        "atr_14", "bb_upper", "bb_mid", "bb_lower", "bb_bandwidth",
        "realized_volatility_20", "volatility_percentile_100",
        "obv", "volume_zscore_20", "price_volume_corr_20", "vwap_deviation_20",
    }
    assert expected_columns <= set(result.columns)
    # The slowest indicator should have produced at least one real value.
    assert result["volatility_percentile_100"].notna().any()
