"""Phase 17: one continuous path across every Tier 1 piece (§13, §16, §17,
§30, §31, §35, §41).

Every phase through 16 is tested in isolation: feature computation, LightGBM
training and inference, signal fusion, risk-gated paper execution, and the
scheduler's stop/target monitor. None of those tests prove the pieces agree
with each other at their seams -- a units mismatch or a sign error between
two individually-correct components would pass every one of them and still
be wrong. This test drives the real chain end to end and asserts on the
final state:

    candles -> technical features -> LightGBM training -> a fused Signal
    -> a person reads it and places a manual paper trade against the risk
    engine -> the scheduler's price monitor carries it to a take-profit
    exit -> a Trade row with the right numbers and the right signal_id.

Marked ``integration``: requires a reachable PostgreSQL, skipped otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from sqlalchemy import select

from app.config.risk_config import RiskConfig
from app.ml.training import run_training_job
from app.models.enums import PositionStatus, SignalComponentKind
from app.models.market import Candle, TechnicalFeature
from app.models.ml import ModelPrediction, ModelVersion, TrainingRun
from app.models.trading import (
    PaperOrder,
    PaperPosition,
    PortfolioSnapshot,
    RiskEvent,
    Signal,
    SignalComponent,
    Trade,
)
from app.paper_trading.account import monitor_open_positions, open_paper_trade
from app.signals.service import generate_signal
from app.technical.feature_engine import compute_and_store_all
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
D = Decimal


@dataclass
class _FakeTicker:
    symbol: str
    price: Decimal


class _FakeMetadata:
    def has(self, symbol: str) -> bool:
        return False


class _FakeBinanceService:
    """The only surface the execution/monitoring path actually calls."""

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
    for table in (
        PaperOrder,
        PaperPosition,
        Trade,
        PortfolioSnapshot,
        RiskEvent,
        SignalComponent,
        Signal,
        ModelPrediction,
        TrainingRun,
        ModelVersion,
        TechnicalFeature,
        Candle,
    ):
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


def _settings():
    return make_settings(
        models={
            "feature_version": "v1",
            "label_horizon": 3,
            "label_threshold": 0.001,
            "min_training_rows": 50,
            "min_validation_accuracy": 0.0,
            "min_validation_macro_f1": 0.0,
            "fusion_min_confidence": 0.0,
            "fusion_action_margin": 0.0,
        },
        paper_trading={"initial_balance": 1000.0, "slippage_bps": 5.0},
        risk=RiskConfig(cooldown_period_seconds=0),
    )


async def _seed_uptrend_and_train(session, settings) -> float:
    """The same synthetic-uptrend generation Phase 9/13's own tests use --
    reused here, not reinvented, so this test's data isn't a special case."""
    rng = np.random.default_rng(1)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    count = 400
    trend = np.cumsum(rng.choice([1.0, -1.0], size=count, p=[0.7, 0.3])) * 0.5
    close = 100 + trend + rng.normal(0, 0.3, count)

    session.add_all(
        [
            Candle(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                open_time=start + timedelta(hours=i),
                close_time=start + timedelta(hours=i + 1),
                open=float(close[i]),
                high=float(close[i] + 0.2),
                low=float(close[i] - 0.2),
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
    outcome = await run_training_job(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)
    assert outcome.model_version is not None
    return float(close[-1])


async def test_the_full_chain_from_candles_to_a_closed_trade(session):
    settings = _settings()
    last_close = await _seed_uptrend_and_train(session, settings)

    # --- Step 1: fuse a signal from the features + model this seed produced.
    signal = await generate_signal(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)
    assert signal is not None
    assert signal.symbol == SYMBOL
    component_kinds = {c.kind for c in signal.components}
    assert component_kinds == {
        SignalComponentKind.TECHNICAL.value,
        SignalComponentKind.LIGHTGBM.value,
    }
    lightgbm_component = next(
        c for c in signal.components if c.kind == SignalComponentKind.LIGHTGBM.value
    )
    assert lightgbm_component.active is True  # the trained model actually got used

    # --- Step 2: a person reads the signal and places a manual paper trade,
    # linking it back to the signal that prompted it (§54: a signal is a
    # recommendation, not an order -- nothing placed this automatically).
    entry_price = D(str(last_close))
    binance = _FakeBinanceService(entry_price)
    stop_price = entry_price * D("0.95")
    take_profit = entry_price * D("1.02")

    result = await open_paper_trade(
        session,
        settings,
        binance,
        symbol=SYMBOL,
        stop_price=stop_price,
        take_profit=take_profit,
        signal_id=signal.id,
    )
    assert result.approved is True
    assert result.position is not None
    assert result.order is not None
    assert result.order.signal_id == signal.id

    rejections = (await session.execute(select(RiskEvent))).scalars().all()
    assert rejections == []  # approved cleanly, nothing to explain

    # --- Step 3: the scheduler's monitor carries the position to its exit
    # without anyone calling close() by hand.
    binance.set_price(take_profit * D("1.001"))
    closed_count = await monitor_open_positions(session, settings, binance)
    assert closed_count == 1

    # --- Step 4: the final state is exactly what the chain should produce.
    position = (
        await session.execute(select(PaperPosition).where(PaperPosition.symbol == SYMBOL))
    ).scalar_one()
    assert position.status == PositionStatus.CLOSED.value
    assert position.signal_id == signal.id

    trades = (await session.execute(select(Trade))).scalars().all()
    assert len(trades) == 1
    trade = trades[0]
    assert trade.symbol == SYMBOL
    assert trade.signal_id == signal.id
    assert trade.exit_reason == "TAKE_PROFIT"
    assert trade.net_pnl > 0  # bought near entry_price, exited near take_profit
    assert trade.fees > 0
    assert trade.slippage_cost > 0

    orders = (
        await session.execute(select(PaperOrder).order_by(PaperOrder.submitted_at))
    ).scalars().all()
    assert len(orders) == 2  # entry fill, exit fill
    assert {order.side for order in orders} == {"BUY", "SELL"}
    assert all(order.signal_id == signal.id for order in orders)

    snapshots = (await session.execute(select(PortfolioSnapshot))).scalars().all()
    assert len(snapshots) >= 2  # at least one from open, one from the monitor tick
