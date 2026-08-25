"""Paper trading engine: risk routing, execution, per-bar exits (§11B, §31, §83)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig
from app.models.enums import EngineState, RiskDecision
from app.paper_trading.simulator import Bar, build_engine
from app.risk.engine import SystemState

D = Decimal
T0 = datetime(2024, 1, 1, tzinfo=UTC)
SYMBOL = "BTCUSDT"

FILTERS = SymbolFilters(min_qty=D("0.00000001"), step_size=D("0.00000001"), min_notional=D("0"))


def engine(balance="1000", **risk_overrides):
    return build_engine(
        initial_balance=D(balance),
        risk=RiskConfig(**risk_overrides),
        fee_rate=D("0.001"),
        slippage_bps=D("5"),
    )


def approve(eng, price=D("100"), stop=D("95"), **kw):
    return eng.evaluate_entry(
        symbol=SYMBOL, entry_price=price, stop_price=stop, filters=FILTERS,
        prices={SYMBOL: price}, now=T0, **kw,
    )


class TestRiskAuthority:
    def test_a_clean_entry_is_approved_and_sized(self):
        assessment = approve(engine())
        assert assessment.approved
        assert assessment.size.quantity > 0

    def test_open_position_refuses_a_rejected_assessment(self):
        """§31: the risk engine's authority must hold even against a bug in
        this module, so the simulator re-checks rather than trusting its
        caller."""
        eng = engine()
        rejected = approve(eng, stop=None)  # no stop -> rejected
        assert not rejected.approved

        with pytest.raises(ValueError, match="requires an APPROVED"):
            eng.open_position(
                assessment=rejected, symbol=SYMBOL, reference_price=D("100"),
                timestamp=T0, filters=FILTERS,
            )

    def test_open_position_refuses_a_paused_assessment(self):
        eng = engine()
        paused = approve(eng, system=SystemState(engine_state=EngineState.EMERGENCY_STOP))
        assert paused.decision is RiskDecision.PAUSED

        with pytest.raises(ValueError, match="requires an APPROVED"):
            eng.open_position(
                assessment=paused, symbol=SYMBOL, reference_price=D("100"),
                timestamp=T0, filters=FILTERS,
            )

    def test_emergency_stop_prevents_any_new_position(self):
        eng = engine()
        approve(eng, system=SystemState(engine_state=EngineState.EMERGENCY_STOP))
        assert eng.portfolio.positions == {}

    def test_rejections_are_counted_for_observability(self):
        eng = engine()
        approve(eng, stop=None)
        approve(eng, stop=None)
        assert eng.rejected_count == 2


class TestExecution:
    def test_opening_creates_a_position_and_spends_cash(self):
        eng = engine()
        before = eng.portfolio.quote_balance
        eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS,
        )
        assert SYMBOL in eng.portfolio.positions
        assert eng.portfolio.quote_balance < before

    def test_the_entry_fill_is_worse_than_the_reference_price(self):
        """Slippage always works against the trader on entry."""
        eng = engine()
        position = eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS,
        )
        assert position.entry_price > D("100")

    def test_closing_books_a_trade_and_returns_cash(self):
        eng = engine()
        eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS,
        )
        trade = eng.close_position(
            symbol=SYMBOL, reference_price=D("110"), timestamp=T0 + timedelta(hours=1),
            reason="TAKE_PROFIT",
        )
        assert trade is not None
        assert SYMBOL not in eng.portfolio.positions
        assert len(eng.portfolio.closed_trades) == 1

    def test_closing_an_absent_position_returns_none(self):
        assert engine().close_position(
            symbol=SYMBOL, reference_price=D("100"), timestamp=T0, reason="EXIT"
        ) is None

    def test_a_round_trip_at_a_flat_price_loses_money_to_costs(self):
        """§87: fees and slippage are real. Break-even price is a loss."""
        eng = engine()
        eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS,
        )
        trade = eng.close_position(
            symbol=SYMBOL, reference_price=D("100"), timestamp=T0, reason="EXIT"
        )
        assert trade.net_pnl < 0
        assert not trade.is_win


class TestBarProcessing:
    def _opened(self, stop=D("95"), target=D("110"), trailing=None):
        eng = engine()
        eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS, stop_loss=stop, take_profit=target,
            trailing_distance=trailing,
        )
        return eng

    def bar(self, high, low, close=None):
        return Bar(
            symbol=SYMBOL, timestamp=T0 + timedelta(hours=1), open=D("100"),
            high=D(high), low=D(low), close=D(close or high),
        )

    def test_a_bar_hitting_the_stop_closes_the_position(self):
        eng = self._opened()
        trade = eng.process_bar(self.bar("101", "94"))
        assert trade is not None
        assert trade.exit_reason == "STOP_LOSS"
        assert SYMBOL not in eng.portfolio.positions

    def test_a_bar_hitting_the_target_closes_the_position(self):
        eng = self._opened()
        trade = eng.process_bar(self.bar("111", "100"))
        assert trade is not None
        assert trade.exit_reason == "TAKE_PROFIT"

    def test_a_quiet_bar_leaves_the_position_open(self):
        eng = self._opened()
        assert eng.process_bar(self.bar("105", "99")) is None
        assert SYMBOL in eng.portfolio.positions

    def test_a_bar_spanning_both_levels_takes_the_stop(self):
        """The pessimistic assumption is the only honest one from OHLC."""
        eng = self._opened()
        trade = eng.process_bar(self.bar("115", "90"))
        assert trade.exit_reason == "STOP_LOSS"

    def test_the_trailing_stop_ratchets_up_on_a_new_high(self):
        eng = self._opened(stop=D("95"), target=None, trailing=D("5"))
        eng.process_bar(self.bar("108", "100"))
        assert eng.portfolio.positions[SYMBOL].stop_loss == D("103")

    def test_the_trail_does_not_raise_the_stop_used_within_the_same_bar(self):
        """§82: ratcheting the stop from a bar's high and then testing that
        same bar's low against the raised stop assumes the high came first,
        which OHLC cannot tell us -- and hands the trade a better exit than
        the data justifies.

        Here the bar runs 100 -> high 108 -> low 100. Trailing by 5 would put
        the stop at 103, and 103 is above the bar's low, so an
        eager-ratcheting implementation exits at 103 (a profit). The honest
        result is no exit at all: the stop in the market during this bar was
        95, and the bar never traded there.
        """
        eng = self._opened(stop=D("95"), target=None, trailing=D("5"))
        trade = eng.process_bar(self.bar("108", "100"))
        assert trade is None, "exited on a stop this bar's own high created"
        assert SYMBOL in eng.portfolio.positions
        # The trail still moves forward for the *next* bar.
        assert eng.portfolio.positions[SYMBOL].stop_loss == D("103")

    def test_processing_a_bar_with_no_position_is_safe(self):
        assert engine().process_bar(self.bar("110", "90")) is None

    def test_excursions_are_recorded_across_bars(self):
        eng = self._opened(stop=None, target=None)
        eng.process_bar(self.bar("108", "97"))
        eng.process_bar(self.bar("104", "96"))
        position = eng.portfolio.positions[SYMBOL]
        assert position.highest_price == D("108")
        assert position.lowest_price == D("96")


class TestCooldownIntegration:
    def test_a_re_entry_inside_the_cooldown_is_rejected(self):
        """The simulator feeds real exit times to the risk engine's cooldown
        rule -- the rule is only meaningful if it is wired to real history."""
        eng = engine()
        eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS,
        )
        eng.close_position(symbol=SYMBOL, reference_price=D("100"), timestamp=T0, reason="EXIT")

        soon = eng.evaluate_entry(
            symbol=SYMBOL, entry_price=D("100"), stop_price=D("95"), filters=FILTERS,
            prices={SYMBOL: D("100")}, now=T0 + timedelta(seconds=60),
        )
        assert not soon.approved
        assert soon.rule == "cooldown_period"

    def test_a_re_entry_after_the_cooldown_is_permitted(self):
        eng = engine()
        eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS,
        )
        eng.close_position(symbol=SYMBOL, reference_price=D("100"), timestamp=T0, reason="EXIT")

        later = eng.evaluate_entry(
            symbol=SYMBOL, entry_price=D("100"), stop_price=D("95"), filters=FILTERS,
            prices={SYMBOL: D("100")},
            now=T0 + timedelta(seconds=RiskConfig().cooldown_period_seconds + 1),
        )
        assert later.approved


class TestForceClose:
    def test_force_close_all_closes_every_position(self):
        eng = engine()
        eng.open_position(
            assessment=approve(eng), symbol=SYMBOL, reference_price=D("100"),
            timestamp=T0, filters=FILTERS,
        )
        closed = eng.force_close_all({SYMBOL: D("105")}, T0 + timedelta(hours=2))
        assert len(closed) == 1
        assert eng.portfolio.positions == {}

    def test_force_close_with_nothing_open_is_a_no_op(self):
        assert engine().force_close_all({}, T0) == []
