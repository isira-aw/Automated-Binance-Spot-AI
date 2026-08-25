"""Paper trading execution against a real database (§11B, §31, §41).

The correctness property under test throughout: the account must behave the
same whether one process handles open-then-close in memory, or two separate
API requests each rehydrate the portfolio from scratch -- the risk engine's
loss-streak and cooldown protections must not reset just because the
in-memory ``PaperTradingEngine`` from the previous request is gone.

Marked ``integration``: requires a reachable PostgreSQL, skipped otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config.risk_config import RiskConfig
from app.core.errors import ValidationError
from app.models.enums import PositionStatus
from app.models.trading import PaperOrder, PaperPosition, PortfolioSnapshot, RiskEvent, Trade
from app.paper_trading.account import close_paper_trade, load_portfolio, open_paper_trade
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

SYMBOL = "BTCUSDT"
D = Decimal


@dataclass
class _FakeTicker:
    symbol: str
    price: Decimal


class _FakeMetadata:
    def has(self, symbol: str) -> bool:
        return False


class _FakeBinanceService:
    """A minimal stand-in: only the surface account.py actually calls."""

    def __init__(self, price: Decimal) -> None:
        self._price = price
        self.metadata = _FakeMetadata()

    async def ticker(self, symbol: str) -> _FakeTicker:
        return _FakeTicker(symbol=symbol, price=self._price)

    def set_price(self, price: Decimal) -> None:
        self._price = price


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
    for table in (PaperOrder, PaperPosition, Trade, PortfolioSnapshot, RiskEvent):
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


def _settings(**risk_overrides):
    risk_overrides.setdefault("cooldown_period_seconds", 0)
    return make_settings(
        paper_trading={"initial_balance": 1000.0, "slippage_bps": 5.0},
        risk=RiskConfig(**risk_overrides),
    )


async def test_a_fresh_account_has_no_open_positions_and_full_balance(session):
    settings = _settings()
    portfolio = await load_portfolio(session, settings)
    assert portfolio.positions == {}
    assert portfolio.quote_balance == D("1000")
    assert portfolio.peak_equity == D("1000")


async def test_opening_a_trade_persists_an_order_and_a_position(session):
    settings = _settings()
    binance = _FakeBinanceService(D("100"))

    result = await open_paper_trade(
        session, settings, binance, symbol=SYMBOL, stop_price=D("95")
    )

    assert result.approved is True
    assert result.order is not None
    assert result.position is not None
    assert result.position.status == PositionStatus.OPEN.value

    orders = (await session.execute(select(PaperOrder))).scalars().all()
    positions = (await session.execute(select(PaperPosition))).scalars().all()
    assert len(orders) == 1
    assert len(positions) == 1
    assert positions[0].symbol == SYMBOL


async def test_opening_reduces_the_rehydrated_balance(session):
    settings = _settings()
    binance = _FakeBinanceService(D("100"))
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))

    portfolio = await load_portfolio(session, settings)
    assert SYMBOL in portfolio.positions
    assert portfolio.quote_balance < settings.paper_trading.initial_balance


async def test_a_second_open_for_the_same_symbol_is_rejected(session):
    settings = _settings()
    binance = _FakeBinanceService(D("100"))
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))

    with pytest.raises(ValidationError):
        await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))


async def test_closing_persists_a_trade_and_frees_the_symbol(session):
    settings = _settings()
    binance = _FakeBinanceService(D("100"))
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))

    binance.set_price(D("110"))
    closed = await close_paper_trade(session, settings, binance, symbol=SYMBOL)
    assert closed.status == PositionStatus.CLOSED.value
    assert closed.realised_pnl is not None
    assert float(closed.realised_pnl) > 0  # bought at 100, sold at 110

    trades = (await session.execute(select(Trade))).scalars().all()
    assert len(trades) == 1
    assert trades[0].net_pnl > 0

    portfolio = await load_portfolio(session, settings)
    assert SYMBOL not in portfolio.positions
    assert portfolio.quote_balance > settings.paper_trading.initial_balance


async def test_closing_with_nothing_open_is_rejected(session):
    settings = _settings()
    binance = _FakeBinanceService(D("100"))
    with pytest.raises(ValidationError):
        await close_paper_trade(session, settings, binance, symbol=SYMBOL)


async def test_cooldown_survives_a_fresh_portfolio_rehydration(session):
    """The core Phase 15b correctness property: cooldown state is derived
    from the ``trades`` table on every call, not carried in memory -- so it
    must still apply even though ``open_paper_trade`` and ``close_paper_trade``
    each construct a brand new ``PaperTradingEngine`` from scratch.
    """
    settings = _settings(cooldown_period_seconds=3600)
    binance = _FakeBinanceService(D("100"))
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))
    await close_paper_trade(session, settings, binance, symbol=SYMBOL)

    result = await open_paper_trade(
        session, settings, binance, symbol=SYMBOL, stop_price=D("95")
    )
    assert result.approved is False
    assert result.rejection_rule is not None

    events = (await session.execute(select(RiskEvent))).scalars().all()
    assert len(events) == 1
    assert events[0].symbol == SYMBOL


async def test_consecutive_loss_streak_survives_rehydration(session):
    """Two losing trades, persisted across separate calls, must still trip
    the streak halt on a third attempt -- not just within one process's
    lifetime.
    """
    settings = _settings(max_consecutive_losses=2)
    binance = _FakeBinanceService(D("100"))

    for _ in range(2):
        await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))
        binance.set_price(D("90"))  # below stop: still a loss when force-closed manually
        await close_paper_trade(session, settings, binance, symbol=SYMBOL)
        binance.set_price(D("100"))

    result = await open_paper_trade(
        session, settings, binance, symbol=SYMBOL, stop_price=D("95")
    )
    assert result.approved is False


async def test_a_stop_at_or_above_entry_is_rejected_and_recorded(session):
    """A long entry needs a stop strictly below entry (app/risk/position_sizing.py);
    without one, sizing has no meaning -- deterministic, unlike a sizing-cap
    rejection which depends on the exact interaction of several parameters.
    """
    settings = _settings()
    binance = _FakeBinanceService(D("100"))

    result = await open_paper_trade(
        session, settings, binance, symbol=SYMBOL, stop_price=D("100")
    )
    assert result.approved is False
    assert result.rejection_rule == "position_sizing"
    assert "stop" in (result.rejection_reason or "").lower()

    events = (await session.execute(select(RiskEvent))).scalars().all()
    assert len(events) == 1
