"""Database schema and persisted-state tests.

Marked ``integration``: these require a reachable PostgreSQL with migrations
applied.  They are skipped automatically when the database is unavailable, so
the unit suite still runs on a bare checkout.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import TradingMode
from app.database.base import Base
from app.models.enums import EngineState
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

# The full table list from MASTER PROMPT §3.
REQUIRED_TABLES = {
    "system_settings", "exchange_settings", "assets", "market_data_metadata",
    "candles", "technical_features", "market_regimes", "patterns",
    "pattern_statistics", "news_articles", "macro_events", "sentiment_scores",
    "model_versions", "model_predictions", "model_metrics", "training_runs",
    "backtest_runs", "backtest_trades", "paper_orders", "paper_positions",
    "live_orders", "live_positions", "trades", "portfolio_snapshots",
    "risk_events", "signals", "signal_components", "execution_events",
    "system_events", "audit_logs",
}


@pytest.fixture
async def engine():
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


async def test_migrations_created_every_required_table(engine):
    async with engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
    missing = REQUIRED_TABLES - tables
    assert not missing, f"Migrations are missing tables: {sorted(missing)}"


async def test_orm_metadata_matches_the_required_table_list():
    """Catches a model being added without its §3 counterpart, and vice versa."""
    assert set(Base.metadata.tables) == REQUIRED_TABLES


async def test_required_indexes_exist_on_the_hot_paths(engine):
    """§102: timestamp/symbol lookups must be indexed."""
    async with engine.connect() as connection:
        candle_indexes = await connection.run_sync(
            lambda sync_conn: inspect(sync_conn).get_indexes("candles")
        )
        signal_indexes = await connection.run_sync(
            lambda sync_conn: inspect(sync_conn).get_indexes("signals")
        )
    candle_columns = {tuple(index["column_names"]) for index in candle_indexes}
    assert ("symbol", "timeframe", "open_time") in candle_columns
    assert any("generated_at" in index["column_names"] for index in signal_indexes)


async def test_state_round_trips_through_the_database(session):
    """§89: restart never assumes a zero starting state."""
    from app.services.app_state import (
        KEY_ENGINE_STATE,
        KEY_TRADING_MODE,
        get_setting,
        load_application_state,
        set_setting,
    )

    await set_setting(session, KEY_TRADING_MODE, TradingMode.PAPER.value)
    await set_setting(session, KEY_ENGINE_STATE, EngineState.RUNNING.value)
    await session.flush()

    assert await get_setting(session, KEY_TRADING_MODE) == "PAPER"
    state = await load_application_state(session, make_settings())
    assert state["mode"] is TradingMode.PAPER
    assert state["engine_state"] is EngineState.RUNNING


async def test_persisted_live_mode_is_not_restored_without_an_arm_flag(session):
    """§12, §106: LIVE is never resumed implicitly after a restart."""
    from app.services.app_state import (
        KEY_LIVE_ARMED,
        KEY_TRADING_MODE,
        load_application_state,
        set_setting,
    )

    await set_setting(session, KEY_TRADING_MODE, TradingMode.LIVE.value)
    await set_setting(session, KEY_LIVE_ARMED, True)
    await session.flush()

    # live_trading_enabled is false in the default configuration.
    state = await load_application_state(session, make_settings())
    assert state["mode"] is TradingMode.PAPER
    assert state["live_armed"] is False


async def test_setting_upsert_does_not_duplicate_rows(session):
    from sqlalchemy import func, select

    from app.models.system import SystemSetting
    from app.services.app_state import set_setting

    await set_setting(session, "test.key", 1)
    await session.flush()
    await set_setting(session, "test.key", 2)
    await session.flush()

    count = await session.scalar(
        select(func.count()).select_from(SystemSetting).where(SystemSetting.key == "test.key")
    )
    assert count == 1
