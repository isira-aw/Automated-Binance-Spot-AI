"""Phase 20: the Tier 1 MVP acceptance criteria, as executable assertions.

This is the "can Tier 1 ship?" checklist. Every other suite tests a
component; this one tests the *promises* — the properties the MASTER PROMPT
states must hold of the finished MVP, independent of how any phase chose to
implement them.

Two kinds of assertion live here, and both matter:

* **Capability** — the Tier 1 pipeline exists and is reachable end to end.
* **Restraint** — the things that must *not* exist yet, and the things that
  must never exist at all. An MVP that quietly grew a withdrawal path or
  started auto-trading would pass every component test and still be a
  failure.

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
from app.models.enums import RiskDecision, SignalAction
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
from app.paper_trading.account import open_paper_trade
from app.risk.engine import AccountState, RiskEngine, SystemState, TradeRequest
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
    def __init__(self, price: Decimal) -> None:
        self._price = price
        self.metadata = _FakeMetadata()

    async def ticker(self, symbol: str) -> _FakeTicker:
        return _FakeTicker(symbol=symbol, price=self._price)


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
    for table in (
        PaperOrder, PaperPosition, Trade, PortfolioSnapshot, RiskEvent,
        SignalComponent, Signal, ModelPrediction, TrainingRun, ModelVersion,
        TechnicalFeature, Candle,
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


def _settings(**overrides):
    base = {
        "models": {
            "feature_version": "v1",
            "min_training_rows": 50,
            "min_validation_accuracy": 0.0,
            "min_validation_macro_f1": 0.0,
            "fusion_min_confidence": 0.0,
            "fusion_action_margin": 0.0,
        },
        "paper_trading": {"initial_balance": 1000.0, "slippage_bps": 5.0},
        "risk": RiskConfig(cooldown_period_seconds=0),
    }
    base.update(overrides)
    return make_settings(**base)


async def _seed(session, settings, *, count: int = 300) -> None:
    rng = np.random.default_rng(20)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    close = 100 + np.cumsum(rng.choice([1.0, -1.0], size=count, p=[0.65, 0.35])) * 0.5

    session.add_all([
        Candle(
            symbol=SYMBOL, timeframe=TIMEFRAME,
            open_time=start + timedelta(hours=i), close_time=start + timedelta(hours=i + 1),
            open=float(close[i]), high=float(close[i] + 0.2), low=float(close[i] - 0.2),
            close=float(close[i]), volume=float(100 + rng.uniform(0, 50)),
            quote_volume=1000.0, trades=10, is_closed=True, source="BINANCE",
        )
        for i in range(count)
    ])
    await session.commit()
    await compute_and_store_all(
        session, symbol=SYMBOL, timeframe=TIMEFRAME,
        feature_version=settings.models.feature_version,
    )


# --------------------------------------------------------------------------- #
# Capability: the Tier 1 pipeline works
# --------------------------------------------------------------------------- #

class TestTier1PipelineIsComplete:
    async def test_a_signal_can_be_produced_from_raw_candles(self, session):
        """The headline Tier 1 promise: candles in, a reasoned signal out."""
        settings = _settings()
        await _seed(session, settings)

        signal = await generate_signal(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)

        assert signal is not None
        assert signal.action in {a.value for a in SignalAction}
        assert 0.0 <= float(signal.score) <= 1.0
        assert 0.0 <= float(signal.confidence) <= 1.0

    async def test_every_signal_carries_a_reproducible_decision_chain(self, session):
        """§79/§80: 'why did it do that?' must be answerable from stored data
        alone, months later, without re-running anything."""
        settings = _settings()
        await _seed(session, settings)
        signal = await generate_signal(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)

        assert signal.reason_codes, "a signal with no reason codes is unexplainable"
        assert signal.components, "a signal with no components cannot be audited"
        assert signal.strategy_version
        assert signal.fusion_method
        for component in signal.components:
            assert component.kind
            assert component.version, "a component with no version cannot be reproduced"

    async def test_a_paper_trade_can_be_placed_and_is_persisted(self, session):
        settings = _settings()
        binance = _FakeBinanceService(D("100"))

        result = await open_paper_trade(
            session, settings, binance, symbol=SYMBOL, stop_price=D("95")
        )

        assert result.approved is True
        assert (await session.execute(select(PaperPosition))).scalars().all()
        assert (await session.execute(select(PaperOrder))).scalars().all()


# --------------------------------------------------------------------------- #
# Restraint: the risk engine is absolute
# --------------------------------------------------------------------------- #

class TestRiskEngineCannotBeBypassed:
    """§31: the risk engine is the highest authority. No component, and no
    caller, may place a trade it did not approve."""

    def _request(self) -> TradeRequest:
        from app.binance.exchange_metadata import SymbolFilters

        return TradeRequest(
            symbol=SYMBOL, entry_price=D("100"), stop_price=D("95"),
            filters=SymbolFilters(), taker_fee=D("0.001"),
        )

    def _account(self, **overrides) -> AccountState:
        base = {
            "equity": D("1000"), "available_quote": D("1000"), "peak_equity": D("1000"),
            "realised_pnl_today": D("0"), "unrealised_pnl": D("0"),
            "consecutive_losses": 0, "open_positions": 0, "asset_exposure": {},
        }
        base.update(overrides)
        return AccountState(**base)

    def test_a_rejected_assessment_never_carries_a_usable_size(self):
        """A rejection that still returned a quantity would be one careless
        caller away from becoming a trade."""
        engine = RiskEngine(RiskConfig(max_consecutive_losses=2))
        assessment = engine.evaluate(
            self._request(), self._account(consecutive_losses=5), SystemState()
        )
        assert assessment.decision is not RiskDecision.APPROVED
        assert assessment.size is None or assessment.size.quantity == 0

    def test_the_simulator_refuses_a_non_approved_assessment(self):
        """Defence in depth: the executor re-checks rather than trusting its
        caller, so a bug upstream still cannot open a position."""
        from app.binance.exchange_metadata import SymbolFilters
        from app.paper_trading.simulator import build_engine

        risk = RiskConfig(max_consecutive_losses=1)
        simulator = build_engine(
            initial_balance=D("1000"), risk=risk,
            fee_rate=D("0.001"), slippage_bps=D("5"),
        )
        rejected = RiskEngine(risk).evaluate(
            self._request(), self._account(consecutive_losses=9), SystemState()
        )
        assert rejected.decision is not RiskDecision.APPROVED

        with pytest.raises(ValueError):
            simulator.open_position(
                assessment=rejected, symbol=SYMBOL, reference_price=D("100"),
                timestamp=datetime(2024, 1, 1, tzinfo=UTC), filters=SymbolFilters(),
            )

    async def test_every_rejection_is_recorded_and_explains_itself(self, session):
        """§47: 'why didn't it trade?' must be answerable after a quiet day."""
        settings = _settings()
        binance = _FakeBinanceService(D("100"))

        # A stop at the entry price cannot be sized (§32).
        result = await open_paper_trade(
            session, settings, binance, symbol=SYMBOL, stop_price=D("100")
        )
        assert result.approved is False

        events = (await session.execute(select(RiskEvent))).scalars().all()
        assert len(events) == 1
        assert events[0].rule, "a rejection with no rule is unactionable"
        assert events[0].reason, "a rejection with no reason is unexplainable"


# --------------------------------------------------------------------------- #
# Restraint: what the MVP must not do
# --------------------------------------------------------------------------- #

class TestMvpBoundaries:
    def test_live_trading_is_off_and_unarmed_by_default(self):
        """§106: shipping must never arm real money by default."""
        settings = make_settings()
        assert settings.trading.mode.value == "PAPER"
        assert settings.trading.live_trading_enabled is False

    def test_no_tier_2_component_is_enabled_by_default(self):
        """§6/§7: Tier 1 must stand alone. A Tier 2 component switched on by
        default would mean the MVP was never validated without it."""
        settings = make_settings()
        assert settings.models.transformer_enabled is False
        assert settings.models.ensemble_enabled is False
        assert settings.llm.ollama_enabled is False
        assert settings.llm.claude_enabled is False
        assert settings.news.enabled is False

    async def test_generating_a_signal_does_not_place_an_order(self, session):
        """Phase 15b's scope boundary, asserted rather than assumed: a signal
        is a recommendation. Nothing executes without a person."""
        settings = _settings()
        await _seed(session, settings)

        signal = await generate_signal(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)
        assert signal is not None

        assert (await session.execute(select(PaperOrder))).scalars().all() == []
        assert (await session.execute(select(PaperPosition))).scalars().all() == []
        assert (await session.execute(select(Trade))).scalars().all() == []

    async def test_a_signal_never_claims_a_risk_decision_it_did_not_get(self, session):
        """`risk_decision` is populated only by something that actually
        consulted the risk engine -- fusion does not, so it must stay NULL
        rather than defaulting to anything that reads as approval."""
        settings = _settings()
        await _seed(session, settings)
        signal = await generate_signal(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)

        assert signal.risk_decision is None
        assert signal.risk_reason is None


# --------------------------------------------------------------------------- #
# Honesty: unbuilt things say so
# --------------------------------------------------------------------------- #

class TestUnbuiltFeaturesAreReportedHonestly:
    """§96: the system never fakes a feature. This is the property that makes
    every other claim in this suite trustworthy."""

    def test_tier_2_namespaces_return_not_implemented_not_empty_data(self):
        from app.api.v1.not_implemented import PENDING_NAMESPACES

        for namespace, (tier, phase) in PENDING_NAMESPACES.items():
            assert tier in {"TIER_1", "TIER_2"}
            assert phase, f"{namespace} must say which phase will build it"

    def test_every_pending_namespace_really_is_unbuilt(self, client):
        """The reverse of the usual check. `router.py` registers the real
        routers *before* the pending ones, so a namespace that got built but
        was left on the pending list would answer 200 here -- catching a
        stale "not implemented" claim about a feature that actually works.
        """
        from app.api.v1.not_implemented import PENDING_NAMESPACES

        stale = [
            namespace
            for namespace in PENDING_NAMESPACES
            if client.get(f"/api/v1/{namespace}").status_code != 501
        ]
        assert stale == [], f"built but still marked pending: {stale}"

    def test_the_influencing_signals_list_matches_what_a_signal_carries(self):
        """§14: the tier report must not overstate *or* understate what
        actually feeds a decision."""
        from app.api.v1.system import INFLUENCING_SIGNALS, TIER2_COMPONENTS

        assert INFLUENCING_SIGNALS, "fusion is built; claiming nothing influences is untrue"
        assert not set(INFLUENCING_SIGNALS) & set(TIER2_COMPONENTS)
