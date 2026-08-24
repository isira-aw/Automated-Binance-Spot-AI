"""Candle-boundary rules (§16) — the basis of every leakage guarantee."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.time_utils import (
    candle_close_time,
    floor_to_timeframe,
    is_candle_closed,
    is_data_stale,
    last_closed_candle_open,
    to_utc,
)


def dt(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("moment", "timeframe", "expected"),
    [
        (dt(2026, 3, 14, 5, 37), "4h", dt(2026, 3, 14, 4, 0)),
        (dt(2026, 3, 14, 3, 59, 59), "4h", dt(2026, 3, 14, 0, 0)),
        (dt(2026, 3, 14, 5, 37), "1h", dt(2026, 3, 14, 5, 0)),
        (dt(2026, 3, 14, 5, 37), "15m", dt(2026, 3, 14, 5, 30)),
        (dt(2026, 3, 14, 5, 37), "1d", dt(2026, 3, 14, 0, 0)),
    ],
)
def test_floor_to_timeframe_uses_utc_boundaries(moment, timeframe, expected):
    assert floor_to_timeframe(moment, timeframe) == expected


def test_4h_candles_close_on_the_documented_utc_boundaries():
    for hour in (0, 4, 8, 12, 16, 20):
        opened = dt(2026, 3, 14, hour, 0)
        assert floor_to_timeframe(opened, "4h") == opened
        assert candle_close_time(opened, "4h").hour == (hour + 4) % 24


def test_candle_is_not_usable_before_its_boundary_passes():
    opened = dt(2026, 3, 14, 4, 0)
    assert not is_candle_closed(opened, "4h", now=dt(2026, 3, 14, 7, 59))
    assert is_candle_closed(opened, "4h", now=dt(2026, 3, 14, 8, 0))


def test_last_closed_candle_open_never_returns_the_open_candle():
    now = dt(2026, 3, 14, 5, 37)
    assert last_closed_candle_open("4h", now=now) == dt(2026, 3, 14, 0, 0)
    assert last_closed_candle_open("15m", now=now) == dt(2026, 3, 14, 5, 15)


def test_lower_timeframe_may_close_while_parent_is_open():
    """A 15m candle may close inside a still-open 4h candle (§16)."""
    now = dt(2026, 3, 14, 5, 37)
    last_15m = last_closed_candle_open("15m", now=now)
    parent_4h = floor_to_timeframe(now, "4h")
    assert is_candle_closed(last_15m, "15m", now=now)
    assert not is_candle_closed(parent_4h, "4h", now=now)


def test_naive_datetimes_are_treated_as_utc_not_local():
    naive = datetime(2026, 3, 14, 5, 37)
    assert to_utc(naive).tzinfo is UTC
    assert to_utc(naive).hour == 5


def test_stale_data_detection():
    now = dt(2026, 3, 14, 5, 37)
    assert is_data_stale(dt(2026, 3, 14, 5, 30), 120, now=now)
    assert not is_data_stale(dt(2026, 3, 14, 5, 36), 120, now=now)


def test_unknown_timeframe_is_rejected():
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        floor_to_timeframe(dt(2026, 3, 14), "7h")
