"""Risk engine authority and every §31 limit.

This is the highest-authority component: no model, no LLM, no frontend
request may bypass it (§31). These tests treat any path to an order that
does not go through an APPROVED assessment as a defect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig
from app.models.enums import EngineState, RiskDecision
from app.risk.engine import (
    RULE_API_FAILURE,
    RULE_ASSET_EXPOSURE,
    RULE_COOLDOWN,
    RULE_EMERGENCY_STOP,
    RULE_ENGINE_PAUSED,
    RULE_MAX_CONSECUTIVE_LOSSES,
    RULE_MAX_DAILY_LOSS,
    RULE_MAX_DRAWDOWN,
    RULE_MAX_POSITIONS,
    RULE_MODEL_HEALTH,
    RULE_PORTFOLIO_EXPOSURE,
    RULE_SLIPPAGE,
    RULE_SPREAD,
    RULE_STALE_DATA,
    RULE_VOLATILITY,
    AccountState,
    RiskEngine,
    SystemState,
    TradeRequest,
)

D = Decimal


def healthy_account(**overrides) -> AccountState:
    base = {
        "equity": D("1000"),
        "available_quote": D("1000"),
        "peak_equity": D("1000"),
        "open_positions": 0,
    }
    base.update(overrides)
    return AccountState(**base)


def healthy_system(**overrides) -> SystemState:
    return SystemState(**{"engine_state": EngineState.RUNNING, **overrides})


def trade(**overrides) -> TradeRequest:
    base = {
        "symbol": "BTCUSDT",
        "entry_price": D("100"),
        "stop_price": D("95"),
        "filters": SymbolFilters(
            min_qty=D("0.00000001"), step_size=D("0.00000001"), min_notional=D("0")
        ),
        "taker_fee": D("0.001"),
    }
    base.update(overrides)
    return TradeRequest(**base)


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine(RiskConfig())


class TestApproval:
    def test_a_clean_trade_is_approved_with_a_size(self, engine):
        result = engine.evaluate(trade(), healthy_account(), healthy_system())
        assert result.decision is RiskDecision.APPROVED
        assert result.approved
        assert result.size is not None and result.size.quantity > 0

    def test_every_decision_carries_a_human_readable_reason(self, engine):
        """§101: the frontend surfaces this text to the operator verbatim."""
        cases = [
            engine.evaluate(trade(), healthy_account(), healthy_system()),
            engine.evaluate(trade(), healthy_account(consecutive_losses=99), healthy_system()),
            engine.evaluate(trade(), healthy_account(), healthy_system(market_data_stale=True)),
            engine.evaluate(trade(spread_fraction=D("0.5")), healthy_account(), healthy_system()),
        ]
        for result in cases:
            assert result.reason
            assert len(result.reason) > 20
            assert result.rule


class TestSystemHealthPauses:
    def test_emergency_stop_pauses_all_trading(self, engine):
        result = engine.evaluate(
            trade(), healthy_account(), healthy_system(engine_state=EngineState.EMERGENCY_STOP)
        )
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_EMERGENCY_STOP

    def test_paused_engine_blocks_new_orders(self, engine):
        result = engine.evaluate(
            trade(), healthy_account(), healthy_system(engine_state=EngineState.PAUSED)
        )
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_ENGINE_PAUSED

    def test_stale_market_data_can_never_trigger_a_trade(self, engine):
        """§44: this is an absolute rule, not a heuristic."""
        result = engine.evaluate(
            trade(),
            healthy_account(),
            healthy_system(
                market_data_stale=True,
                last_market_data_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
        )
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_STALE_DATA

    def test_repeated_api_failures_pause_trading(self, engine):
        threshold = RiskConfig().api_failure_protection_threshold
        result = engine.evaluate(
            trade(), healthy_account(), healthy_system(consecutive_api_failures=threshold)
        )
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_API_FAILURE

    def test_an_unhealthy_model_can_never_trigger_a_trade(self, engine):
        result = engine.evaluate(
            trade(), healthy_account(), healthy_system(model_healthy=False)
        )
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_MODEL_HEALTH

    def test_model_health_gate_can_be_configured_off_without_affecting_others(self):
        engine = RiskEngine(RiskConfig(model_health_protection=False))
        result = engine.evaluate(trade(), healthy_account(), healthy_system(model_healthy=False))
        assert result.decision is RiskDecision.APPROVED
        # ...but stale data is still absolute.
        stale = engine.evaluate(trade(), healthy_account(), healthy_system(market_data_stale=True))
        assert stale.decision is RiskDecision.PAUSED


class TestAccountHalts:
    def test_daily_loss_limit_pauses_trading(self, engine):
        account = healthy_account(realised_pnl_today=D("-50"))  # 5% of 1000
        result = engine.evaluate(trade(), account, healthy_system())
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_MAX_DAILY_LOSS

    def test_unrealised_losses_count_toward_the_daily_limit(self, engine):
        """Money lost on an open position is lost, closed or not."""
        account = healthy_account(unrealised_pnl=D("-50"))
        result = engine.evaluate(trade(), account, healthy_system())
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_MAX_DAILY_LOSS

    def test_a_profitable_day_does_not_trip_the_loss_limit(self, engine):
        account = healthy_account(realised_pnl_today=D("500"))
        assert engine.evaluate(trade(), account, healthy_system()).approved

    def test_max_drawdown_pauses_trading(self, engine):
        account = healthy_account(equity=D("800"), available_quote=D("800"), peak_equity=D("1000"))
        result = engine.evaluate(trade(), account, healthy_system())
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_MAX_DRAWDOWN

    def test_consecutive_losses_pause_trading(self, engine):
        limit = RiskConfig().max_consecutive_losses
        account = healthy_account(consecutive_losses=limit)
        result = engine.evaluate(trade(), account, healthy_system())
        assert result.decision is RiskDecision.PAUSED
        assert result.rule == RULE_MAX_CONSECUTIVE_LOSSES

    def test_no_martingale_losses_never_increase_the_risked_amount(self, engine):
        """§56: risk per trade is a constant fraction of equity; a losing
        streak must never size *up* to recover."""
        fresh = engine.evaluate(trade(), healthy_account(), healthy_system())
        after_losses = engine.evaluate(
            trade(), healthy_account(consecutive_losses=1), healthy_system()
        )
        assert fresh.size.risk_amount == after_losses.size.risk_amount


class TestPerTradeRejections:
    def test_a_wide_spread_rejects_the_trade(self, engine):
        result = engine.evaluate(
            trade(spread_fraction=D("0.05")), healthy_account(), healthy_system()
        )
        assert result.decision is RiskDecision.REJECTED
        assert result.rule == RULE_SPREAD

    def test_excess_volatility_rejects_the_trade(self, engine):
        result = engine.evaluate(trade(atr_fraction=D("0.5")), healthy_account(), healthy_system())
        assert result.decision is RiskDecision.REJECTED
        assert result.rule == RULE_VOLATILITY

    def test_excess_expected_slippage_rejects_the_trade(self, engine):
        result = engine.evaluate(
            trade(expected_slippage=D("0.05")), healthy_account(), healthy_system()
        )
        assert result.decision is RiskDecision.REJECTED
        assert result.rule == RULE_SLIPPAGE

    def test_cooldown_rejects_a_too_soon_re_entry(self, engine):
        result = engine.evaluate(
            trade(seconds_since_last_exit=10), healthy_account(), healthy_system()
        )
        assert result.decision is RiskDecision.REJECTED
        assert result.rule == RULE_COOLDOWN

    def test_an_elapsed_cooldown_permits_the_trade(self, engine):
        elapsed = RiskConfig().cooldown_period_seconds + 1
        assert engine.evaluate(
            trade(seconds_since_last_exit=elapsed), healthy_account(), healthy_system()
        ).approved

    def test_position_count_limit_rejects_a_new_entry(self, engine):
        limit = RiskConfig().max_simultaneous_positions
        result = engine.evaluate(trade(), healthy_account(open_positions=limit), healthy_system())
        assert result.decision is RiskDecision.REJECTED
        assert result.rule == RULE_MAX_POSITIONS

    def test_a_filled_asset_exposure_cap_rejects(self, engine):
        account = healthy_account(asset_exposure={"BTCUSDT": D("500")})
        result = engine.evaluate(trade(), account, healthy_system())
        assert result.decision is RiskDecision.REJECTED
        assert result.rule == RULE_ASSET_EXPOSURE

    def test_a_filled_portfolio_exposure_cap_rejects(self, engine):
        account = healthy_account(
            asset_exposure={"ETHUSDT": D("400"), "BNBUSDT": D("400")}, open_positions=0
        )
        result = engine.evaluate(trade(), account, healthy_system())
        assert result.decision is RiskDecision.REJECTED
        assert result.rule == RULE_PORTFOLIO_EXPOSURE

    def test_an_uneconomic_size_rejects_rather_than_forcing_the_order(self, engine):
        """§32/§88: a trade too small to execute legally is rejected, never
        rounded up to the exchange minimum."""
        # peak_equity must match: a small account is not the same as a
        # large one that just lost 96%, which would (correctly) trip drawdown.
        tiny = healthy_account(equity=D("40"), available_quote=D("40"), peak_equity=D("40"))
        result = engine.evaluate(
            trade(
                filters=SymbolFilters(
                    min_notional=D("10"), min_qty=D("0.001"), step_size=D("0.001")
                )
            ),
            tiny,
            healthy_system(),
        )
        assert result.decision is RiskDecision.REJECTED
        assert result.size is not None and not result.size.approved


class TestRuleOrdering:
    """Account/system halts must be reported before per-trade rejections, or
    an operator reads 'that trade was bad' when the truth is 'trading is
    stopped'."""

    def test_emergency_stop_is_reported_even_when_the_trade_is_also_invalid(self, engine):
        result = engine.evaluate(
            trade(spread_fraction=D("0.9"), seconds_since_last_exit=0),
            healthy_account(open_positions=99),
            healthy_system(engine_state=EngineState.EMERGENCY_STOP),
        )
        assert result.rule == RULE_EMERGENCY_STOP
        assert result.decision is RiskDecision.PAUSED

    def test_system_health_is_reported_before_account_halts(self, engine):
        result = engine.evaluate(
            trade(),
            healthy_account(consecutive_losses=99),
            healthy_system(market_data_stale=True),
        )
        assert result.rule == RULE_STALE_DATA

    def test_account_halts_are_reported_before_per_trade_rejections(self, engine):
        result = engine.evaluate(
            trade(spread_fraction=D("0.9")),
            healthy_account(consecutive_losses=99),
            healthy_system(),
        )
        assert result.rule == RULE_MAX_CONSECUTIVE_LOSSES
        assert result.decision is RiskDecision.PAUSED


class TestAuthority:
    def test_no_rejected_or_paused_assessment_ever_carries_a_usable_size(self, engine):
        """The only way to get a tradeable size is an APPROVED decision. A
        caller that ignores `decision` still cannot build an order."""
        blocked = [
            engine.evaluate(
                trade(),
                healthy_account(),
                healthy_system(engine_state=EngineState.EMERGENCY_STOP),
            ),
            engine.evaluate(trade(), healthy_account(consecutive_losses=99), healthy_system()),
            engine.evaluate(trade(spread_fraction=D("0.9")), healthy_account(), healthy_system()),
            engine.evaluate(trade(), healthy_account(open_positions=99), healthy_system()),
        ]
        for result in blocked:
            assert result.decision is not RiskDecision.APPROVED
            assert not result.approved
            assert result.size is None or not result.size.approved
            assert result.size is None or result.size.quantity == 0

    def test_the_engine_reads_limits_from_config_not_hardcoded_values(self):
        """§31: RiskConfig is the single source of truth. Tightening a limit
        in config must change the engine's behaviour with no code change."""
        permissive = RiskEngine(RiskConfig(max_simultaneous_positions=5))
        strict = RiskEngine(RiskConfig(max_simultaneous_positions=1))
        account = healthy_account(open_positions=1)
        assert permissive.evaluate(trade(), account, healthy_system()).approved
        assert not strict.evaluate(trade(), account, healthy_system()).approved
