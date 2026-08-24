"""UTC time and candle-boundary helpers (§16, §72).

Local/laptop time is never used for candle-boundary logic.  Every timestamp in
this system is timezone-aware UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def to_utc(value: datetime) -> datetime:
    """Normalise any datetime to timezone-aware UTC.

    Naive datetimes are *assumed* to already be UTC — the ingestion layer is
    responsible for never producing local-time naive values.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def timeframe_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:  # pragma: no cover - guarded by config validation
        raise ValueError(f"Unsupported timeframe: {timeframe!r}") from exc


def floor_to_timeframe(moment: datetime, timeframe: str) -> datetime:
    """Return the open time of the candle that ``moment`` falls inside.

    Boundaries are anchored to the Unix epoch in UTC, which matches Binance's
    kline boundaries for every timeframe this system uses (a 4h candle opens at
    00:00/04:00/08:00... UTC).
    """
    moment = to_utc(moment)
    seconds = timeframe_seconds(timeframe)
    epoch_seconds = int(moment.timestamp())
    return datetime.fromtimestamp(
        epoch_seconds - (epoch_seconds % seconds), tz=UTC
    )


def candle_close_time(open_time: datetime, timeframe: str) -> datetime:
    """Exclusive close boundary of the candle that opened at ``open_time``."""
    return to_utc(open_time) + timedelta(seconds=timeframe_seconds(timeframe))


def is_candle_closed(
    open_time: datetime, timeframe: str, *, now: datetime | None = None
) -> bool:
    """Whether a candle is fully closed and therefore usable as a feature.

    Per §16 a candle may only be used as model input once its own boundary has
    passed.  Callers that have Binance's ``kline.is_closed`` flag should trust
    that flag instead; this is the fallback for historical data.
    """
    reference = to_utc(now) if now is not None else utc_now()
    return reference >= candle_close_time(open_time, timeframe)


def last_closed_candle_open(timeframe: str, *, now: datetime | None = None) -> datetime:
    """Open time of the most recent *closed* candle for ``timeframe``."""
    reference = to_utc(now) if now is not None else utc_now()
    return floor_to_timeframe(reference, timeframe) - timedelta(
        seconds=timeframe_seconds(timeframe)
    )


def is_data_stale(
    last_update: datetime, max_age_seconds: int, *, now: datetime | None = None
) -> bool:
    """Stale-data protection (§31 ``stale_data_protection``, §44)."""
    reference = to_utc(now) if now is not None else utc_now()
    return (reference - to_utc(last_update)).total_seconds() > max_age_seconds
