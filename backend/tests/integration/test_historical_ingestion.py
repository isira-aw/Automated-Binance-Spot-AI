"""Historical ingestion and integrity validation against a real database (§17).

Marked ``integration``: requires a reachable PostgreSQL with migrations
applied, skipped automatically otherwise.  The upsert, resumability and gap
detection logic all depend on real SQL semantics (ON CONFLICT, the xmax
insert/update distinction) that a mock cannot stand in for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.binance.market_data import MarketDataService
from app.binance.mock import MockBinanceServer
from app.binance.rest_client import BinanceRestClient
from app.models.market import Candle, MarketDataMetadata
from app.services.data_integrity import validate_symbol_timeframe
from app.services.historical_ingestion import backfill_symbol_timeframe
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
        # Ingestion commits internally, so roll back is not enough --
        # remove anything this test wrote.
        await session.rollback()
        await session.execute(Candle.__table__.delete())
        await session.execute(MarketDataMetadata.__table__.delete())
        await session.commit()


def market_data_for(mock: MockBinanceServer) -> MarketDataService:
    settings = make_settings()
    client = BinanceRestClient(settings)
    client.get = mock.get  # type: ignore[method-assign]
    client.time_sync.observe(
        sent_ms=mock.server_time_ms, server_ms=mock.server_time_ms, received_ms=mock.server_time_ms
    )
    return MarketDataService(client, settings)


async def test_backfill_persists_only_closed_candles(session):
    """Full history (from EARLIEST_POSSIBLE_MS) exceeds one page; this checks
    the persisted rows are all closed, not that the whole backfill finishes."""
    mock = MockBinanceServer()
    market_data = market_data_for(mock)

    result = await backfill_symbol_timeframe(
        session, market_data, symbol="BTCUSDT", timeframe="1h", max_pages=1
    )

    assert result.candles_inserted > 0

    rows = (await session.execute(select(Candle).where(Candle.symbol == "BTCUSDT"))).scalars().all()
    assert all(row.is_closed for row in rows)
    assert len(rows) == result.candles_inserted


async def test_backfill_reaches_present_when_history_fits_one_page(session, monkeypatch):
    """When the full history is small enough, backfill finishes in one page
    and reports reached_present."""
    import app.services.historical_ingestion as ingestion_module

    mock = MockBinanceServer()
    market_data = market_data_for(mock)
    monkeypatch.setattr(
        ingestion_module, "EARLIEST_POSSIBLE_MS", mock.server_time_ms - 500 * 3600 * 1000
    )

    result = await backfill_symbol_timeframe(
        session, market_data, symbol="BTCUSDT", timeframe="1h", max_pages=1
    )

    assert result.reached_present is True
    assert result.candles_inserted > 0


async def test_backfill_updates_metadata_coverage(session):
    mock = MockBinanceServer()
    market_data = market_data_for(mock)

    await backfill_symbol_timeframe(
        session, market_data, symbol="ETHUSDT", timeframe="4h", max_pages=1
    )

    meta = (
        await session.execute(
            select(MarketDataMetadata).where(
                MarketDataMetadata.symbol == "ETHUSDT", MarketDataMetadata.timeframe == "4h"
            )
        )
    ).scalar_one()
    assert meta.candle_count > 0
    assert meta.first_candle_open is not None
    assert meta.last_candle_open is not None
    assert meta.first_candle_open <= meta.last_candle_open


async def test_a_second_backfill_resumes_rather_than_restarting(session):
    """The core resumability guarantee: re-running must not refetch history
    that is already durable, and must not duplicate rows."""
    mock = MockBinanceServer()
    market_data = market_data_for(mock)

    first = await backfill_symbol_timeframe(
        session, market_data, symbol="BNBUSDT", timeframe="1h", max_pages=1
    )
    count_after_first = (
        await session.execute(select(Candle).where(Candle.symbol == "BNBUSDT"))
    ).scalars().all()

    # Advance the mock's clock so new candles exist to backfill, mirroring
    # time actually passing between two real runs.
    mock.server_time_ms += 3 * 3600 * 1000
    second = await backfill_symbol_timeframe(
        session, market_data, symbol="BNBUSDT", timeframe="1h", max_pages=1
    )
    count_after_second = (
        await session.execute(select(Candle).where(Candle.symbol == "BNBUSDT"))
    ).scalars().all()

    assert second.candles_inserted > 0
    assert len(count_after_second) == len(count_after_first) + second.candles_inserted
    assert first.candles_inserted + second.candles_inserted == len(count_after_second)


async def test_upsert_does_not_duplicate_on_conflict(session):
    """Ingesting the identical page twice must update in place, not duplicate
    -- the ON CONFLICT path, exercised directly rather than only through the
    resume logic."""
    from app.services.historical_ingestion import _upsert_candles

    mock = MockBinanceServer()
    market_data = market_data_for(mock)
    klines = await market_data.closed_klines("BTCUSDT", "1h", limit=5)

    inserted_1, updated_1 = await _upsert_candles(session, klines, source="BINANCE")
    await session.commit()
    inserted_2, updated_2 = await _upsert_candles(session, klines, source="BINANCE")
    await session.commit()

    assert inserted_1 == len(klines)
    assert updated_1 == 0
    assert inserted_2 == 0
    assert updated_2 == len(klines)

    rows = (await session.execute(select(Candle).where(Candle.symbol == "BTCUSDT"))).scalars().all()
    assert len(rows) == len(klines)


async def test_a_stopped_backfill_resumes_from_the_interruption_point(session):
    """§ resumability: a run bounded to one page, resumed later, must not
    restart from scratch -- this is the ingestion analogue of the
    partial-restore recovery the master prompt requires elsewhere."""
    mock = MockBinanceServer()
    market_data = market_data_for(mock)
    mock.server_time_ms += 5000 * 3600 * 1000  # ample history to span pages

    first = await backfill_symbol_timeframe(
        session, market_data, symbol="BTCUSDT", timeframe="1h", max_pages=1
    )
    assert first.reached_present is False  # one page could not cover it all

    second = await backfill_symbol_timeframe(
        session, market_data, symbol="BTCUSDT", timeframe="1h", max_pages=1
    )

    first_rows = (
        await session.execute(select(Candle.open_time).where(Candle.symbol == "BTCUSDT"))
    ).scalars().all()
    assert second.candles_inserted > 0
    assert len(set(first_rows)) == len(first_rows)  # no duplicate open_times


async def test_integrity_detects_a_gap(session):
    now = datetime(2024, 1, 1, tzinfo=UTC)
    session.add_all(
        [
            _candle("BTCUSDT", "1h", now),
            # a 3-hour gap: two candles missing
            _candle("BTCUSDT", "1h", now + timedelta(hours=4)),
        ]
    )
    await session.commit()

    report = await validate_symbol_timeframe(session, symbol="BTCUSDT", timeframe="1h")
    assert report.missing_candles == 3
    assert report.is_clean is True  # a gap alone is not corruption


async def test_integrity_detects_ohlc_violation(session):
    now = datetime(2024, 1, 1, tzinfo=UTC)
    bad = _candle("BTCUSDT", "1h", now, high=90, low=110, open=100, close=100)
    session.add(bad)
    await session.commit()

    report = await validate_symbol_timeframe(session, symbol="BTCUSDT", timeframe="1h")
    assert report.ohlc_violations
    assert report.is_clean is False


async def test_integrity_detects_non_positive_values(session):
    now = datetime(2024, 1, 1, tzinfo=UTC)
    session.add(_candle("BTCUSDT", "1h", now, close=0))
    await session.commit()

    report = await validate_symbol_timeframe(session, symbol="BTCUSDT", timeframe="1h")
    assert report.non_positive_values
    assert report.is_clean is False


async def test_integrity_detects_misaligned_timestamp(session):
    off_boundary = datetime(2024, 1, 1, 0, 17, tzinfo=UTC)
    session.add(_candle("BTCUSDT", "1h", off_boundary))
    await session.commit()

    report = await validate_symbol_timeframe(session, symbol="BTCUSDT", timeframe="1h")
    assert report.misaligned_timestamps
    assert report.is_clean is False


async def test_integrity_report_persists_to_metadata(session):
    now = datetime(2024, 1, 1, tzinfo=UTC)
    session.add(_candle("BTCUSDT", "1h", now))
    await session.commit()

    await validate_symbol_timeframe(session, symbol="BTCUSDT", timeframe="1h")

    meta = (
        await session.execute(
            select(MarketDataMetadata).where(
                MarketDataMetadata.symbol == "BTCUSDT", MarketDataMetadata.timeframe == "1h"
            )
        )
    ).scalar_one()
    assert meta.last_integrity_check is not None
    assert meta.integrity_report is not None
    assert meta.integrity_report["is_clean"] is True


async def test_clean_history_reports_zero_missing_and_is_clean(session):
    now = datetime(2024, 1, 1, tzinfo=UTC)
    session.add_all([_candle("BTCUSDT", "1h", now + timedelta(hours=i)) for i in range(5)])
    await session.commit()

    report = await validate_symbol_timeframe(session, symbol="BTCUSDT", timeframe="1h")
    assert report.missing_candles == 0
    assert report.is_clean is True
    assert report.candle_count == 5


def _candle(
    symbol: str,
    timeframe: str,
    open_time: datetime,
    *,
    open: float = 100,
    high: float = 101,
    low: float = 99,
    close: float = 100.5,
) -> Candle:
    from app.core.time_utils import timeframe_seconds

    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_time,
        close_time=open_time + timedelta(seconds=timeframe_seconds(timeframe)),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=10,
        quote_volume=1000,
        trades=5,
        is_closed=True,
        source="BINANCE",
    )
