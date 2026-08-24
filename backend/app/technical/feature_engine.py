"""Persists computed indicators to ``technical_features`` (§19, §78).

Two entry points:

- :func:`compute_latest` — incremental, called when a new candle closes.
  Loads a bounded lookback window and stores only the newest row.
- :func:`compute_and_store_all` — bulk, called after a historical backfill or
  on demand.  Computes over the whole stored history at once (indicators need
  their full preceding window to be correct) and upserts every row that has
  at least one non-null value.

Both trust their caller to have already restricted the input to closed
candles (§16, §18) — this module does not re-check ``is_closed`` itself, the
same division of responsibility the candle-reading endpoints already use.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging_config import get_logger
from app.engines.market_structure import compute_all as compute_structure
from app.models.market import Candle, TechnicalFeature
from app.technical.indicators import REQUIRED_LOOKBACK
from app.technical.indicators import compute_all as compute_indicators

logger = get_logger("technical.feature_engine")

# Extra history beyond the slowest indicator's own requirement, so its first
# real value isn't right at the edge of the loaded window.
LOOKBACK_BUFFER = 50
DEFAULT_LOOKBACK = REQUIRED_LOOKBACK + LOOKBACK_BUFFER


def _compute_combined(df: pd.DataFrame) -> pd.DataFrame:
    """Indicator values (§19) and market structure fields (§20) side by side
    in one feature vector.  Structure is computed independently of any model
    -- joining it here is only storage convenience, not a dependency on the
    indicator values it sits next to.
    """
    indicators = compute_indicators(df)
    structure = compute_structure(df)
    return indicators.join(structure)


def _clean_for_json(value: Any) -> Any:
    """NaN/Inf are not valid JSON; store them as an explicit null instead of
    letting the driver either reject them or silently write a non-standard
    token that Postgres JSONB cannot store (§18: missing history must read as
    missing, never as a fabricated number)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


async def _load_candles(
    session: AsyncSession, *, symbol: str, timeframe: str, limit: int | None
) -> pd.DataFrame:
    query = (
        select(Candle)
        .where(Candle.symbol == symbol, Candle.timeframe == timeframe, Candle.is_closed.is_(True))
        .order_by(Candle.open_time.desc())
    )
    if limit is not None:
        query = query.limit(limit)

    rows = (await session.execute(query)).scalars().all()
    rows = list(reversed(rows))  # chronological order, required by the indicators

    return pd.DataFrame(
        {
            "open_time": [row.open_time for row in rows],
            "open": [float(row.open) for row in rows],
            "high": [float(row.high) for row in rows],
            "low": [float(row.low) for row in rows],
            "close": [float(row.close) for row in rows],
            "volume": [float(row.volume) for row in rows],
        }
    )


async def _upsert_features(
    session: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    feature_version: str,
    open_times: list,
    feature_rows: list[dict[str, Any]],
) -> int:
    if not open_times:
        return 0

    rows = [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": open_time,
            "feature_version": feature_version,
            "features": {key: _clean_for_json(value) for key, value in feature_row.items()},
        }
        for open_time, feature_row in zip(open_times, feature_rows, strict=True)
    ]

    stmt = pg_insert(TechnicalFeature).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_technical_features_symbol",
        set_={"features": stmt.excluded.features},
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def compute_latest(
    session: AsyncSession, *, symbol: str, timeframe: str, feature_version: str
) -> bool:
    """Compute and store the feature vector for the most recently closed candle.

    Returns ``False`` (and stores nothing) only when there is no candle at all
    to compute from.  A feature row is stored even in a symbol's first hour:
    some indicators (OBV) are warmup-free by construction and are already
    meaningful, while every other field is correctly ``null`` until its own
    window is satisfied -- callers already have to check individual fields for
    availability regardless, so gating the whole row on "is anything at all
    non-null" would only hide a distinction consumers must handle anyway.
    """
    df = await _load_candles(session, symbol=symbol, timeframe=timeframe, limit=DEFAULT_LOOKBACK)
    if df.empty:
        return False

    features = _compute_combined(df.set_index("open_time"))
    latest = features.iloc[-1]

    await _upsert_features(
        session,
        symbol=symbol,
        timeframe=timeframe,
        feature_version=feature_version,
        open_times=[df["open_time"].iloc[-1]],
        feature_rows=[latest.to_dict()],
    )
    return True


async def compute_and_store_all(
    session: AsyncSession, *, symbol: str, timeframe: str, feature_version: str
) -> int:
    """Recompute and store features for every closed candle currently stored.

    One feature row per candle -- the same "store it, let individual fields be
    null" reasoning as :func:`compute_latest` applies here too.  Used after a
    historical backfill (§67 phase 6/7 boundary) so newly ingested history
    gets features without waiting for new live candles.
    """
    df = await _load_candles(session, symbol=symbol, timeframe=timeframe, limit=None)
    if df.empty:
        return 0

    features = _compute_combined(df.set_index("open_time"))
    stored = await _upsert_features(
        session,
        symbol=symbol,
        timeframe=timeframe,
        feature_version=feature_version,
        open_times=list(df["open_time"]),
        feature_rows=[row.to_dict() for _, row in features.iterrows()],
    )
    logger.info(
        "Computed technical features for stored history",
        extra={
            "event_type": "features_backfilled",
            "symbol": symbol,
            "timeframe": timeframe,
            "rows_stored": stored,
        },
    )
    return stored
