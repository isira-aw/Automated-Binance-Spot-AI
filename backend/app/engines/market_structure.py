"""Market structure engine (§20).

Detects swing highs/lows, HH/HL/LH/LL sequences, Break of Structure (BOS),
Change of Character (CHoCH), support/resistance, and breakout/breakdown/false
breakout — all from price action alone, independent of any ML model (§20's
own requirement, not just this system's general preference for it).

Causality is the hard part here, and it works differently from the indicator
module. A swing high at bar ``i`` is only *knowable* once ``window`` bars after
it have failed to exceed it — so every structure signal derived from a swing
is attributed to the bar where it becomes confirmed, never to the swing's own
bar. A false breakout goes through the same delay a second time: the breakout
itself is known immediately, but "was it false" needs
``FALSE_BREAKOUT_WINDOW`` further bars to answer, so that flag is likewise
attributed to its confirmation bar, not the breakout bar. Getting this
attribution wrong is exactly how a system silently reintroduces §18 leakage
while still being able to say "no centred windows here" with a straight face —
so it is the one thing this module's tests check most aggressively, using the
same truncated-prefix method as the indicator module's no-lookahead tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

SWING_WINDOW = 5
FALSE_BREAKOUT_WINDOW = 3


class SwingKind(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class Trend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SwingPoint:
    """A confirmed swing high/low.

    ``index`` is the bar the swing occurred at; ``confirmed_index`` is the bar
    at which enough subsequent price action existed to confirm it — always
    ``index + window``, and always what callers must use for causal ordering.
    """

    index: int
    confirmed_index: int
    kind: SwingKind
    price: float


def find_swing_points(
    high: pd.Series, low: pd.Series, *, window: int = SWING_WINDOW
) -> list[SwingPoint]:
    """Fractal-style swing detection: a swing high/low compared to ``window``
    bars on each side.  Only returns swings whose confirming bars are within
    the given series — nothing here ever looks past the end of ``high``/``low``.
    """
    n = len(high)
    swings: list[SwingPoint] = []
    for i in range(window, n - window):
        window_high = high.iloc[i - window : i + window + 1]
        if high.iloc[i] == window_high.max() and (window_high == high.iloc[i]).sum() == 1:
            swings.append(SwingPoint(i, i + window, SwingKind.HIGH, float(high.iloc[i])))

        window_low = low.iloc[i - window : i + window + 1]
        if low.iloc[i] == window_low.min() and (window_low == low.iloc[i]).sum() == 1:
            swings.append(SwingPoint(i, i + window, SwingKind.LOW, float(low.iloc[i])))

    swings.sort(key=lambda swing: swing.confirmed_index)
    return swings


@dataclass
class _State:
    trend: Trend = Trend.UNKNOWN
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    prev_high: SwingPoint | None = None
    prev_low: SwingPoint | None = None
    resistance: float | None = None
    support: float | None = None
    pending_breaks: list[tuple[int, str]] | None = None  # (breakout_bar, direction)

    def __post_init__(self) -> None:
        if self.pending_breaks is None:
            self.pending_breaks = []


def compute_all(df: pd.DataFrame, *, window: int = SWING_WINDOW) -> pd.DataFrame:
    """Bar-by-bar market structure fields, aligned to ``df``'s index.

    ``df`` must contain only closed candles in chronological order, the same
    contract :mod:`app.technical.indicators` uses (§16, §18) — this function
    does not re-check it.

    A single forward pass over the bars: at each bar, only swings already
    confirmed as of that bar (``confirmed_index <= i``) are consulted, which is
    what keeps every emitted value causal.
    """
    high, low, close = df["high"], df["low"], df["close"]
    n = len(df)

    swings = find_swing_points(high, low, window=window)
    swings_by_confirmation: dict[int, list[SwingPoint]] = {}
    for swing in swings:
        swings_by_confirmation.setdefault(swing.confirmed_index, []).append(swing)

    trend = [Trend.UNKNOWN] * n
    is_hh = [False] * n
    is_hl = [False] * n
    is_lh = [False] * n
    is_ll = [False] * n
    bos = [False] * n
    choch = [False] * n
    resistance: list[float | None] = [None] * n
    support: list[float | None] = [None] * n
    breakout = [False] * n
    breakdown = [False] * n
    false_breakout = [False] * n

    state = _State()
    assert state.pending_breaks is not None

    for i in range(n):
        # 1. Resolve any swings newly confirmed at this bar, updating the
        #    HH/HL/LH/LL sequence and the prevailing trend.
        for swing in swings_by_confirmation.get(i, []):
            if swing.kind is SwingKind.HIGH:
                if state.last_high is not None:
                    if swing.price > state.last_high.price:
                        is_hh[i] = True
                    else:
                        is_lh[i] = True
                state.prev_high, state.last_high = state.last_high, swing
                state.resistance = swing.price
            else:
                if state.last_low is not None:
                    if swing.price > state.last_low.price:
                        is_hl[i] = True
                    else:
                        is_ll[i] = True
                state.prev_low, state.last_low = state.last_low, swing
                state.support = swing.price

            if is_hh[i] or is_hl[i]:
                new_trend = Trend.BULLISH
            elif is_lh[i] or is_ll[i]:
                new_trend = Trend.BEARISH
            else:
                new_trend = state.trend

            if state.trend is not Trend.UNKNOWN and new_trend is not state.trend:
                choch[i] = True
            state.trend = new_trend

        trend[i] = state.trend
        resistance[i] = state.resistance
        support[i] = state.support

        # 2. Breakout / breakdown against the *previously confirmed* level —
        #    never the level this same bar might just have set above.
        level_resistance = state.resistance
        level_support = state.support
        if level_resistance is not None and close.iloc[i] > level_resistance:
            breakout[i] = True
            if state.trend is Trend.BULLISH:
                bos[i] = True
            state.pending_breaks.append((i, "breakout"))
        if level_support is not None and close.iloc[i] < level_support:
            breakdown[i] = True
            if state.trend is Trend.BEARISH:
                bos[i] = True
            state.pending_breaks.append((i, "breakdown"))

        # 3. Resolve any breakout/breakdown whose confirmation window has now
        #    elapsed: false if price closed back inside the level it broke.
        still_pending = []
        for break_bar, direction in state.pending_breaks:
            if i - break_bar < FALSE_BREAKOUT_WINDOW:
                still_pending.append((break_bar, direction))
                continue
            broke_level = resistance[break_bar] if direction == "breakout" else support[break_bar]
            if broke_level is None:
                continue
            reverted = (
                close.iloc[i] < broke_level
                if direction == "breakout"
                else close.iloc[i] > broke_level
            )
            if reverted:
                false_breakout[i] = True
        state.pending_breaks = still_pending

    return pd.DataFrame(
        {
            "structure_trend": [t.value for t in trend],
            "is_higher_high": is_hh,
            "is_higher_low": is_hl,
            "is_lower_high": is_lh,
            "is_lower_low": is_ll,
            "break_of_structure": bos,
            "change_of_character": choch,
            "resistance_level": resistance,
            "support_level": support,
            "breakout": breakout,
            "breakdown": breakdown,
            "false_breakout": false_breakout,
        },
        index=df.index,
    )
