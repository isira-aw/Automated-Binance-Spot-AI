"""Technical indicators (§19).

Every indicator here is causal: the value at row ``i`` depends only on rows
``<= i``.  This is what makes §18 (no future information in features) hold at
the indicator level — a rolling window aligned to the current row, an EMA's
recursive definition, and a diff against the previous row are all causal by
construction, and every function in this module is built only from those
primitives.  ``tests/unit/test_indicators_no_lookahead.py`` checks this
directly: recomputing on a truncated series must reproduce the same values as
the same prefix of the full series.

Input: a DataFrame with columns ``open, high, low, close, volume`` and a
monotonically increasing index (chronological order is required — this module
does not sort).  Output: a DataFrame with each indicator as a column, aligned
to the same index (leading rows without enough history are NaN, not 0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _require_ohlcv(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing OHLCV columns: {missing}")
    if len(df) == 0:
        raise ValueError("DataFrame has no rows.")


# --- Trend -------------------------------------------------------------


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period, min_periods=period).mean()


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False, min_periods=period).mean()


def wma(close: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1)
    return close.rolling(window=period, min_periods=period).apply(
        lambda window: float(np.dot(window, weights) / weights.sum()), raw=True
    )


def rolling_vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int
) -> pd.Series:
    """Volume-weighted average price over a rolling window.

    A true session VWAP resets at a session boundary; this system has no
    exchange session concept for a 24/7 market, so a rolling window is used
    instead — anchored to "now minus N candles", which stays causal.
    """
    typical_price = (high + low + close) / 3
    pv = typical_price * volume
    return pv.rolling(window=period, min_periods=period).sum() / volume.rolling(
        window=period, min_periods=period
    ).sum()


def directional_movement(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int
) -> pd.DataFrame:
    """ADX and the +DI/-DI lines it is built from (Wilder's smoothing)."""
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )

    tr = _true_range(high, low, close)
    atr_smoothed = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = (
        100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_smoothed
    )
    minus_di = (
        100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_smoothed
    )

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": adx})


# --- Momentum ------------------------------------------------------------


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing is an EMA with alpha = 1/period.
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    # avg_loss == 0 means no down moves in the window: RSI is 100 by
    # convention, not undefined -- a plain division would produce NaN and
    # silently drop the strongest possible trend signal from the feature set.
    result = result.where(avg_loss != 0, 100.0)
    # The genuinely undefined case (no gains and no losses at all, i.e. a flat
    # price) is left as NaN rather than guessing a value.
    result = result.where(~((avg_gain == 0) & (avg_loss == 0)), np.nan)
    return result


def macd(
    close: pd.Series, *, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    line = fast_ema - slow_ema
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame(
        {"macd": line, "macd_signal": signal_line, "macd_histogram": line - signal_line}
    )


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, *, k_period: int = 14, d_period: int = 3
) -> pd.DataFrame:
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()
    denominator = (highest_high - lowest_low).replace(0, np.nan)
    percent_k = 100 * (close - lowest_low) / denominator
    percent_d = percent_k.rolling(window=d_period, min_periods=d_period).mean()
    return pd.DataFrame({"stoch_k": percent_k, "stoch_d": percent_d})


def roc(close: pd.Series, period: int = 12) -> pd.Series:
    shifted = close.shift(period)
    return 100 * (close - shifted) / shifted.replace(0, np.nan)


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    typical_price = (high + low + close) / 3
    sma_tp = typical_price.rolling(window=period, min_periods=period).mean()
    mean_deviation = typical_price.rolling(window=period, min_periods=period).apply(
        lambda window: float(np.abs(window - window.mean()).mean()), raw=True
    )
    return (typical_price - sma_tp) / (0.015 * mean_deviation.replace(0, np.nan))


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    highest_high = high.rolling(window=period, min_periods=period).max()
    lowest_low = low.rolling(window=period, min_periods=period).min()
    denominator = (highest_high - lowest_low).replace(0, np.nan)
    return -100 * (highest_high - close) / denominator


# --- Volatility ------------------------------------------------------------


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = _true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def bollinger_bands(close: pd.Series, *, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    return pd.DataFrame(
        {"bb_upper": upper, "bb_mid": mid, "bb_lower": lower, "bb_bandwidth": bandwidth}
    )


def realized_volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """Annualised-in-spirit rolling std of log returns.

    Not scaled by a trading-day count (crypto trades 24/7, so "annualised"
    has no single agreed convention) -- left as the raw rolling std of log
    returns, which is what every consumer of this feature actually needs: a
    comparable, unit-consistent volatility measure.
    """
    log_returns = np.log(close / close.shift(1))
    return log_returns.rolling(window=period, min_periods=period).std(ddof=0)


def volatility_percentile(atr_series: pd.Series, period: int = 100) -> pd.Series:
    """Where current ATR sits within its own recent history, in [0, 1].

    A technical-feature-level volatility signal, distinct from the Tier 2
    market regime engine (§23) -- this is one raw input a regime classifier
    could use later, not a regime classification itself.
    """
    def _rank(window: np.ndarray) -> float:
        current = window[-1]
        if len(window) <= 1:
            return np.nan
        return float((window <= current).sum() - 1) / (len(window) - 1)

    return atr_series.rolling(window=period, min_periods=period).apply(_rank, raw=True)


# --- Volume ------------------------------------------------------------


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume).cumsum()


def volume_zscore(volume: pd.Series, period: int = 20) -> pd.Series:
    """How anomalous the current volume bar is versus its recent history."""
    mean = volume.rolling(window=period, min_periods=period).mean()
    std = volume.rolling(window=period, min_periods=period).std(ddof=0)
    return (volume - mean) / std.replace(0, np.nan)


def price_volume_correlation(close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    price_change = close.diff()
    return price_change.rolling(window=period, min_periods=period).corr(volume)


def vwap_deviation(close: pd.Series, vwap_series: pd.Series) -> pd.Series:
    """Fractional distance of close from the rolling VWAP."""
    return (close - vwap_series) / vwap_series.replace(0, np.nan)


# --- Orchestration -------------------------------------------------------

# Lookback each indicator needs before its first non-NaN value.  The feature
# engine uses the maximum of these to decide how many candles it must load.
REQUIRED_LOOKBACK = 210  # covers the slowest indicator (volatility_percentile: ATR(14) + 100)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Compute every §19 indicator category for one symbol/timeframe series.

    ``df`` must already contain only closed candles, in chronological order
    (§16, §18) -- this function trusts its caller on that; it is the feature
    engine's job to select rows that way, not this module's.
    """
    _require_ohlcv(df)
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    vwap20 = rolling_vwap(high, low, close, volume, period=20)
    atr14 = atr(high, low, close, period=14)

    features = pd.DataFrame(index=df.index)
    features["sma_20"] = sma(close, 20)
    features["sma_50"] = sma(close, 50)
    features["ema_12"] = ema(close, 12)
    features["ema_26"] = ema(close, 26)
    features["wma_20"] = wma(close, 20)
    features["vwap_20"] = vwap20
    features = features.join(directional_movement(high, low, close, period=14))

    features["rsi_14"] = rsi(close, 14)
    features = features.join(macd(close))
    features = features.join(stochastic(high, low, close))
    features["roc_12"] = roc(close, 12)
    features["cci_20"] = cci(high, low, close, 20)
    features["williams_r_14"] = williams_r(high, low, close, 14)

    features["atr_14"] = atr14
    features = features.join(bollinger_bands(close))
    features["realized_volatility_20"] = realized_volatility(close, 20)
    features["volatility_percentile_100"] = volatility_percentile(atr14, 100)

    features["obv"] = obv(close, volume)
    features["volume_zscore_20"] = volume_zscore(volume, 20)
    features["price_volume_corr_20"] = price_volume_correlation(close, volume, 20)
    features["vwap_deviation_20"] = vwap_deviation(close, vwap20)

    return features
