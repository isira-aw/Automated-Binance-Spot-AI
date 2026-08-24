"""Risk decisions are persisted so 'why didn't it trade?' is answerable (§31, §47)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig
from app.models.enums import EngineState, RiskDecision
from app.models.trading import RiskEvent
from app.risk.engine import AccountState, RiskEngine, SystemState, TradeRequest
from app.risk.events import record_risk_event
from tests.conftest import make_settings

pytestmark = pytest.mark.integration
D = Decimal


@pytest.fixture
async def engine_db():
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = make_settings()
    db = create_async_engine(settings.database.async_url)
    try:
        async with db.connect():
            pass
    except Exception as exc:
        await db.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    yield db
    await db.dispose()


@pytest.fixture
async def session(engine_db):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine_db, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
        await session.execute(RiskEvent.__table__.delete())
        await session.commit()


def _trade() -> TradeRequest:
    return TradeRequest(
        symbol="BTCUSDT",
        entry_price=D("100"),
        stop_price=D("95"),
        filters=SymbolFilters(min_qty=D("0.00000001"), step_size=D("0.00000001")),
        taker_fee=D("0.001"),
    )


def _account(**over) -> AccountState:
    return AccountState(
        **{"equity": D("1000"), "available_quote": D("1000"), "peak_equity": D("1000"), **over}
    )


async def test_a_rejection_is_persisted_with_its_reason(session):
    engine = RiskEngine(RiskConfig())
    assessment = engine.evaluate(
        TradeRequest(**{**_trade().__dict__, "spread_fraction": D("0.9")}),
        _account(),
        SystemState(),
    )
    assert assessment.decision is RiskDecision.REJECTED

    await record_risk_event(session, assessment, symbol="BTCUSDT")

    row = (await session.execute(select(RiskEvent))).scalar_one()
    assert row.decision == "REJECTED"
    assert row.rule == "spread_protection"
    assert "spread" in row.reason.lower()
    assert row.symbol == "BTCUSDT"


async def test_a_pause_is_persisted(session):
    engine = RiskEngine(RiskConfig())
    assessment = engine.evaluate(
        _trade(), _account(), SystemState(engine_state=EngineState.EMERGENCY_STOP)
    )
    await record_risk_event(session, assessment, symbol="BTCUSDT")

    row = (await session.execute(select(RiskEvent))).scalar_one()
    assert row.decision == "PAUSED"
    assert row.rule == "emergency_stop"


async def test_an_approval_is_not_written_as_a_risk_event(session):
    """Approvals become orders; the order and its execution_events row are
    the record of that path. Writing both would duplicate one fact across
    two tables that could later disagree."""
    engine = RiskEngine(RiskConfig())
    assessment = engine.evaluate(_trade(), _account(), SystemState())
    assert assessment.approved

    result = await record_risk_event(session, assessment, symbol="BTCUSDT")
    assert result is None

    rows = (await session.execute(select(RiskEvent))).scalars().all()
    assert rows == []


async def test_details_are_preserved_for_later_analysis(session):
    engine = RiskEngine(RiskConfig())
    assessment = engine.evaluate(_trade(), _account(consecutive_losses=99), SystemState())
    await record_risk_event(session, assessment, symbol="BTCUSDT")

    row = (await session.execute(select(RiskEvent))).scalar_one()
    assert row.details is not None
    assert "consecutive_losses" in row.details
