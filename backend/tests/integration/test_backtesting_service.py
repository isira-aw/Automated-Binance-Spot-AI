"""Backtest orchestration against a real database (§35, §41, §82).

Marked ``integration``: requires a reachable PostgreSQL, skipped otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app.backtesting.service import run_backtest
from app.core.errors import ValidationError
from app.models.backtesting import BacktestRun, BacktestTrade
from app.models.market import Candle, TechnicalFeature
from app.technical.feature_engine import compute_and_store_all
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"


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


async def _truncate(session) -> None:
    """Clean before and after: cleaning only afterwards makes a test depend on
    the database starting empty, which fails spuriously against existing data.
    """
    for table in (BacktestTrade, BacktestRun, TechnicalFeature, Candle):
        await session.execute(table.__table__.delete())
    await session.commit()


@pytest.fixture
async def session(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await _truncate(session)
        yield session
        await session.rollback()
        await _truncate(session)


@pytest.fixture
def settings():
    return make_settings(
        models={
            "feature_version": "v1",
            "fusion_min_confidence": 0.0,
            "fusion_action_margin": 0.0,
        },
    )


async def _seed(
    session, settings, *, count: int = 300, trend_up: bool = True
) -> tuple[datetime, datetime]:
    rng = np.random.default_rng(3)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    drift = 0.6 if trend_up else -0.6
    trend = np.cumsum(np.full(count, drift)) + rng.normal(0, 0.4, count)
    close = 100 + trend

    session.add_all(
        [
            Candle(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                open_time=start + timedelta(hours=i),
                close_time=start + timedelta(hours=i + 1),
                open=float(close[i]),
                high=float(close[i] + 0.3),
                low=float(close[i] - 0.3),
                close=float(close[i]),
                volume=float(100 + rng.uniform(0, 50)),
                quote_volume=1000.0,
                trades=10,
                is_closed=True,
                source="BINANCE",
            )
            for i in range(count)
        ]
    )
    await session.commit()
    await compute_and_store_all(
        session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version=settings.models.feature_version
    )
    return start, start + timedelta(hours=count - 1)


async def test_no_candles_in_range_is_rejected(session, settings):
    range_start = datetime(2030, 1, 1, tzinfo=UTC)
    range_end = range_start + timedelta(days=1)
    with pytest.raises(ValidationError):
        await run_backtest(
            session, settings, symbol=SYMBOL, timeframe=TIMEFRAME,
            range_start=range_start, range_end=range_end,
        )


async def test_a_run_is_persisted_with_its_seven_disclosures(session, settings):
    start, end = await _seed(session, settings)
    run = await run_backtest(
        session, settings, symbol=SYMBOL, timeframe=TIMEFRAME, range_start=start, range_end=end
    )

    assert run.id is not None
    assert run.status == "COMPLETED"
    assert run.symbols == [SYMBOL]
    assert run.metrics is not None
    assert run.assumptions is not None
    disclosures = {
        "fee_model", "slippage_model", "fill_model", "lookahead_prevention",
        "intrabar_assumption", "liquidity_assumption", "survivorship_note",
    }
    assert disclosures.issubset(run.assumptions.keys())

    stored = (
        await session.execute(select(BacktestRun).where(BacktestRun.id == run.id))
    ).scalar_one()
    assert stored.job_id == run.job_id


async def test_a_trending_series_produces_trades_with_costs_applied(session, settings):
    start, end = await _seed(session, settings, count=400, trend_up=True)
    run = await run_backtest(
        session, settings, symbol=SYMBOL, timeframe=TIMEFRAME, range_start=start, range_end=end
    )

    # A strong, low-noise uptrend should give the technical-only reference
    # strategy at least one entry to work with.
    assert len(run.trades) >= 1
    for trade in run.trades:
        assert trade.fees > 0
        assert trade.slippage_cost > 0


async def test_too_few_candles_is_rejected(session, settings):
    start, _end = await _seed(session, settings, count=5)
    with pytest.raises(ValidationError):
        await run_backtest(
            session, settings, symbol=SYMBOL, timeframe=TIMEFRAME,
            range_start=start, range_end=start,
        )


async def test_the_bar_cap_is_enforced(session, settings):
    start, end = await _seed(session, settings, count=300)
    capped = make_settings(
        models={
            "feature_version": "v1", "fusion_min_confidence": 0.0, "fusion_action_margin": 0.0,
        },
        backtesting={"max_bars": 10},
    )
    with pytest.raises(ValidationError):
        await run_backtest(
            session, capped, symbol=SYMBOL, timeframe=TIMEFRAME, range_start=start, range_end=end
        )


async def test_a_completed_run_is_queryable_with_its_trades(session, settings):
    start, end = await _seed(session, settings, count=400, trend_up=True)
    run = await run_backtest(
        session, settings, symbol=SYMBOL, timeframe=TIMEFRAME, range_start=start, range_end=end
    )

    trades = (
        await session.execute(select(BacktestTrade).where(BacktestTrade.run_id == run.id))
    ).scalars().all()
    assert len(trades) == len(run.trades)
