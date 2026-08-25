"""The Phase 16 scheduler tick against a real database (§16, §31, §41).

``monitor_open_positions`` is the continuous check a manually-placed paper
position never had before Phase 16: previously a stop/target was only
checked at the moment someone called ``close``. These tests exercise it the
same way the scheduler calls it, one tick at a time.

Marked ``integration``: requires a reachable PostgreSQL, skipped otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config.risk_config import RiskConfig
from app.models.trading import PaperOrder, PaperPosition, PortfolioSnapshot, RiskEvent, Trade
from app.paper_trading.account import (
    close_paper_trade,
    load_portfolio,
    monitor_open_positions,
    open_paper_trade,
)
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

SYMBOL = "BTCUSDT"
OTHER_SYMBOL = "ETHUSDT"
D = Decimal


@dataclass
class _FakeTicker:
    symbol: str
    price: Decimal


class _FakeMetadata:
    def has(self, symbol: str) -> bool:
        return False


class _FakeBinanceService:
    def __init__(self, prices: dict[str, Decimal]) -> None:
        self._prices = prices
        self.metadata = _FakeMetadata()
        self.fail_symbols: set[str] = set()

    async def ticker(self, symbol: str) -> _FakeTicker:
        if symbol in self.fail_symbols:
            raise RuntimeError(f"No connectivity to price {symbol}.")
        return _FakeTicker(symbol=symbol, price=self._prices[symbol])

    def set_price(self, symbol: str, price: Decimal) -> None:
        self._prices[symbol] = price


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


async def test_no_open_positions_is_a_no_op(session):
    settings = _settings()
    binance = _FakeBinanceService({})
    closed = await monitor_open_positions(session, settings, binance)
    assert closed == 0


async def test_no_binance_service_is_a_no_op(session):
    settings = _settings()
    binance = _FakeBinanceService({SYMBOL: D("100")})
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))

    closed = await monitor_open_positions(session, settings, None)
    assert closed == 0

    portfolio = await load_portfolio(session, settings)
    assert SYMBOL in portfolio.positions  # untouched


async def test_a_price_at_or_below_stop_closes_the_position(session):
    settings = _settings()
    binance = _FakeBinanceService({SYMBOL: D("100")})
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))

    binance.set_price(SYMBOL, D("94"))
    closed = await monitor_open_positions(session, settings, binance)
    assert closed == 1

    portfolio = await load_portfolio(session, settings)
    assert SYMBOL not in portfolio.positions

    trades = (await session.execute(select(Trade))).scalars().all()
    assert len(trades) == 1
    assert trades[0].exit_reason == "STOP_LOSS"
    # Fills at the stop, adjusted for slippage against the trader -- not the
    # tick price (94) that triggered it.
    assert D("94.9") < trades[0].exit_price < D("95")


async def test_a_price_at_or_above_target_closes_the_position(session):
    settings = _settings()
    binance = _FakeBinanceService({SYMBOL: D("100")})
    await open_paper_trade(
        session, settings, binance, symbol=SYMBOL, stop_price=D("95"), take_profit=D("110")
    )

    binance.set_price(SYMBOL, D("111"))
    closed = await monitor_open_positions(session, settings, binance)
    assert closed == 1

    trades = (await session.execute(select(Trade))).scalars().all()
    assert trades[0].exit_reason == "TAKE_PROFIT"
    # Fills at the target, adjusted for slippage against the trader.
    assert D("109.5") < trades[0].exit_price < D("110")


async def test_a_price_between_stop_and_target_ratchets_the_trailing_stop(session):
    settings = _settings()
    binance = _FakeBinanceService({SYMBOL: D("100")})
    await open_paper_trade(
        session, settings, binance, symbol=SYMBOL, stop_price=D("95"), trailing_distance=D("5")
    )

    binance.set_price(SYMBOL, D("120"))
    closed = await monitor_open_positions(session, settings, binance)
    assert closed == 0

    row = (
        await session.execute(select(PaperPosition).where(PaperPosition.symbol == SYMBOL))
    ).scalar_one()
    assert float(row.stop_loss) == 115.0  # 120 - 5, raised from 95

    # A second tick at a lower price must not lower the stop back down.
    binance.set_price(SYMBOL, D("116"))
    closed_again = await monitor_open_positions(session, settings, binance)
    assert closed_again == 0
    await session.refresh(row)
    assert float(row.stop_loss) == 115.0


async def test_one_symbols_price_failure_does_not_block_the_others(session):
    settings = _settings(max_simultaneous_positions=2)
    binance = _FakeBinanceService({SYMBOL: D("100"), OTHER_SYMBOL: D("100")})
    first = await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))
    second = await open_paper_trade(
        session, settings, binance, symbol=OTHER_SYMBOL, stop_price=D("95")
    )
    assert first.approved and second.approved

    binance.fail_symbols.add(SYMBOL)
    binance.set_price(OTHER_SYMBOL, D("90"))  # below stop
    closed = await monitor_open_positions(session, settings, binance)
    assert closed == 1

    portfolio = await load_portfolio(session, settings)
    assert SYMBOL in portfolio.positions
    assert OTHER_SYMBOL not in portfolio.positions


async def test_a_tick_records_a_portfolio_snapshot(session):
    settings = _settings()
    binance = _FakeBinanceService({SYMBOL: D("100")})
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))

    before = (await session.execute(select(PortfolioSnapshot))).scalars().all()
    await monitor_open_positions(session, settings, binance)
    after = (await session.execute(select(PortfolioSnapshot))).scalars().all()

    assert len(after) == len(before) + 1
    assert after[-1].venue == "PAPER"


async def test_a_position_closed_between_ticks_is_skipped_not_errored(session):
    settings = _settings()
    binance = _FakeBinanceService({SYMBOL: D("100")})
    await open_paper_trade(session, settings, binance, symbol=SYMBOL, stop_price=D("95"))
    await close_paper_trade(session, settings, binance, symbol=SYMBOL)

    # Nothing open any more; a tick must be a clean no-op, not an error.
    closed = await monitor_open_positions(session, settings, binance)
    assert closed == 0
