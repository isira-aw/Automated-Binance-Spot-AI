"""Feature engine persistence against a real database (§19, §78).

Marked ``integration``: requires a reachable PostgreSQL with migrations
applied, skipped automatically otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app.models.market import Candle, TechnicalFeature
from app.technical.feature_engine import compute_and_store_all, compute_latest
from tests.conftest import make_settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = make_settings()
    engine = create_async_engine(settings.database.async_url)
    try:
        async with engine.connect():
            pass
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
        await session.execute(TechnicalFeature.__table__.delete())
        await session.execute(Candle.__table__.delete())
        await session.commit()


async def _seed_candles(session, *, symbol: str, timeframe: str, count: int, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    close = 100 + np.cumsum(rng.normal(0, 1, count))
    session.add_all(
        [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=start + timedelta(hours=i),
                close_time=start + timedelta(hours=i + 1),
                open=float(close[i]),
                high=float(close[i] + 1),
                low=float(close[i] - 1),
                close=float(close[i]),
                volume=100.0 + i,
                quote_volume=1000.0,
                trades=10,
                is_closed=True,
                source="BINANCE",
            )
            for i in range(count)
        ]
    )
    await session.commit()


async def test_compute_latest_with_no_candles_stores_nothing(session):
    stored = await compute_latest(
        session, symbol="BTCUSDT", timeframe="1h", feature_version="v1"
    )
    assert stored is False

    rows = (await session.execute(select(TechnicalFeature))).scalars().all()
    assert rows == []


async def test_compute_latest_with_short_history_still_stores_warmup_free_indicators(session):
    """OBV needs no warm-up window, so a row is stored even in a symbol's
    first hours -- with every windowed indicator correctly null."""
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=5)
    stored = await compute_latest(
        session, symbol="BTCUSDT", timeframe="1h", feature_version="v1"
    )
    assert stored is True

    row = (await session.execute(select(TechnicalFeature))).scalar_one()
    assert row.features["obv"] is not None
    assert row.features["sma_20"] is None


async def test_compute_latest_stores_exactly_one_row(session):
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    stored = await compute_latest(
        session, symbol="BTCUSDT", timeframe="1h", feature_version="v1"
    )
    assert stored is True

    rows = (await session.execute(select(TechnicalFeature))).scalars().all()
    assert len(rows) == 1
    assert rows[0].features["sma_20"] is not None


async def test_compute_latest_matches_the_most_recent_candle(session):
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    await compute_latest(session, symbol="BTCUSDT", timeframe="1h", feature_version="v1")

    latest_candle_open = (
        await session.execute(select(Candle.open_time).order_by(Candle.open_time.desc()).limit(1))
    ).scalar_one()
    row = (await session.execute(select(TechnicalFeature))).scalar_one()
    assert row.open_time == latest_candle_open


async def test_re_running_compute_latest_upserts_not_duplicates(session):
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    await compute_latest(session, symbol="BTCUSDT", timeframe="1h", feature_version="v1")
    await compute_latest(session, symbol="BTCUSDT", timeframe="1h", feature_version="v1")

    rows = (await session.execute(select(TechnicalFeature))).scalars().all()
    assert len(rows) == 1


async def test_compute_and_store_all_covers_the_whole_history(session):
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    stored = await compute_and_store_all(
        session, symbol="BTCUSDT", timeframe="1h", feature_version="v1"
    )
    assert stored > 0

    rows = (await session.execute(select(TechnicalFeature))).scalars().all()
    assert len(rows) == stored
    # Every row must correspond to an actual candle -- no fabricated rows.
    candle_times = set(
        (await session.execute(select(Candle.open_time))).scalars().all()
    )
    assert {row.open_time for row in rows} <= candle_times


async def test_compute_and_store_all_produces_one_row_per_candle(session):
    """Every closed candle gets a feature row, even the very first one --
    windowed indicators are null there, not absent from the table entirely."""
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    stored = await compute_and_store_all(
        session, symbol="BTCUSDT", timeframe="1h", feature_version="v1"
    )
    assert stored == 250

    earliest_candle = (
        await session.execute(select(Candle.open_time).order_by(Candle.open_time).limit(1))
    ).scalar_one()
    earliest_feature = (
        await session.execute(
            select(TechnicalFeature.open_time).order_by(TechnicalFeature.open_time).limit(1)
        )
    ).scalar_one()
    assert earliest_feature == earliest_candle

    earliest_row = (
        await session.execute(
            select(TechnicalFeature).order_by(TechnicalFeature.open_time).limit(1)
        )
    ).scalar_one()
    assert earliest_row.features["sma_20"] is None
    assert earliest_row.features["obv"] is not None


async def test_nan_values_are_stored_as_json_null_not_a_string_or_number(session):
    """§18: missing history must read as missing, never as a fabricated value."""
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=25)
    await compute_and_store_all(session, symbol="BTCUSDT", timeframe="1h", feature_version="v1")

    earliest = (
        await session.execute(
            select(TechnicalFeature).order_by(TechnicalFeature.open_time).limit(1)
        )
    ).scalar_one()
    # sma_50 cannot have a value yet with only 25 candles.
    assert earliest.features["sma_50"] is None
    assert isinstance(earliest.features["sma_50"], type(None))


async def test_feature_version_is_recorded_and_filterable(session):
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    await compute_and_store_all(session, symbol="BTCUSDT", timeframe="1h", feature_version="v2")

    rows = (
        await session.execute(
            select(TechnicalFeature).where(TechnicalFeature.feature_version == "v2")
        )
    ).scalars().all()
    assert len(rows) > 0
    assert all(row.feature_version == "v2" for row in rows)


async def test_different_feature_versions_coexist(session):
    """A model pinned to v1 must never see v2 rows and vice versa (§78)."""
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    await compute_and_store_all(session, symbol="BTCUSDT", timeframe="1h", feature_version="v1")
    await compute_and_store_all(session, symbol="BTCUSDT", timeframe="1h", feature_version="v2")

    v1_count = await session.scalar(
        select(TechnicalFeature).where(TechnicalFeature.feature_version == "v1")
    )
    v2_count = await session.scalar(
        select(TechnicalFeature).where(TechnicalFeature.feature_version == "v2")
    )
    assert v1_count is not None
    assert v2_count is not None

    all_rows = (await session.execute(select(TechnicalFeature))).scalars().all()
    versions = {row.feature_version for row in all_rows}
    assert versions == {"v1", "v2"}


async def test_open_candle_is_never_used_for_features(session):
    """§16, §18: only closed candles may reach the feature engine."""
    await _seed_candles(session, symbol="BTCUSDT", timeframe="1h", count=250)
    now = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=250)
    session.add(
        Candle(
            symbol="BTCUSDT",
            timeframe="1h",
            open_time=now,
            close_time=now + timedelta(hours=1),
            open=999999,  # deliberately absurd, so leakage would be obvious
            high=999999,
            low=999999,
            close=999999,
            volume=1,
            is_closed=False,
            source="BINANCE",
        )
    )
    await session.commit()

    await compute_and_store_all(session, symbol="BTCUSDT", timeframe="1h", feature_version="v1")

    rows = (await session.execute(select(TechnicalFeature))).scalars().all()
    assert all(row.open_time != now for row in rows)
    # And the absurd value must not have leaked into any close-based average.
    for row in rows:
        for key, value in row.features.items():
            if value is not None and key.startswith(("sma", "ema", "wma", "vwap")):
                assert value < 10000, f"{key} looks contaminated by the open candle: {value}"
