"""Portfolio accounting: balances, P&L, drawdown, MAE/MFE (§41, §42)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper_trading.portfolio import Portfolio

D = Decimal
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def fresh(balance="1000") -> Portfolio:
    return Portfolio(quote_balance=D(balance), initial_balance=D(balance))


def buy(p, *, qty="1", price="100", fee="0", symbol="BTCUSDT", **kw):
    return p.open_position(
        symbol=symbol, quantity=D(qty), price=D(price), fee=D(fee), timestamp=T0, **kw
    )


def sell(p, *, price="100", fee="0", slip="0", symbol="BTCUSDT", reason="EXIT", when=None):
    return p.close_position(
        symbol=symbol, price=D(price), fee=D(fee), slippage_cost=D(slip),
        timestamp=when or T0, reason=reason,
    )


class TestOpening:
    def test_opening_deducts_cost_and_fee_from_cash(self):
        p = fresh()
        buy(p, qty="2", fee="0.2")
        assert p.quote_balance == D("799.8")
        assert p.total_fees == D("0.2")

    def test_opening_beyond_the_balance_is_refused(self):
        p = fresh("100")
        with pytest.raises(ValueError, match="exceeds balance"):
            buy(p, qty="10", fee="1")

    def test_a_duplicate_position_is_refused(self):
        p = fresh()
        buy(p)
        with pytest.raises(ValueError, match="already open"):
            buy(p)


class TestClosingAndPnl:
    def test_a_winning_trade_books_net_profit_after_fees(self):
        p = fresh()
        buy(p, qty="2", fee="0.2")
        trade = sell(p, price="110", fee="0.22", reason="TAKE_PROFIT", when=T0 + timedelta(hours=1))
        assert trade.gross_pnl == D("20")
        assert trade.fees == D("0.42")
        assert trade.net_pnl == D("19.58")
        assert trade.is_win

    def test_a_gross_win_eaten_by_fees_is_not_a_win(self):
        """§41: win rate is measured net of costs, not gross."""
        p = fresh()
        buy(p, fee="1")
        trade = sell(p, price="100.5", fee="1")
        assert trade.gross_pnl > 0
        assert trade.net_pnl < 0
        assert not trade.is_win

    def test_closing_returns_proceeds_to_cash(self):
        p = fresh()
        buy(p, qty="2")
        sell(p)
        assert p.quote_balance == D("1000")

    def test_closing_an_absent_position_is_refused(self):
        with pytest.raises(ValueError, match="No open position"):
            sell(fresh())


class TestValuation:
    def test_equity_is_cash_plus_marked_positions(self):
        p = fresh()
        buy(p, qty="2")
        assert p.equity({"BTCUSDT": D("110")}) == D("1020")

    def test_a_missing_price_values_at_entry_not_zero(self):
        """A data gap must not show a phantom loss that could trip the
        drawdown halt on its own."""
        p = fresh()
        buy(p, qty="2")
        assert p.equity({}) == D("1000")

    def test_drawdown_is_measured_from_peak_equity(self):
        p = fresh()
        p.update_peak_equity({})
        p.quote_balance = D("800")
        assert p.drawdown_fraction({}) == pytest.approx(D("0.2"))

    def test_drawdown_is_never_negative_when_above_peak(self):
        p = fresh()
        p.quote_balance = D("1200")
        assert p.drawdown_fraction({}) == 0


class TestRiskEngineInputs:
    def test_consecutive_losses_counts_back_to_the_last_win(self):
        p = fresh()
        for price, reason in ((D("90"), "L"), (D("90"), "L"), (D("110"), "W"), (D("90"), "L")):
            buy(p)
            sell(p, price=str(price), reason=reason)
        assert p.consecutive_losses == 1

    def test_a_clean_slate_has_no_loss_streak(self):
        assert fresh().consecutive_losses == 0

    def test_asset_exposure_reports_marked_value_per_symbol(self):
        p = fresh()
        buy(p, qty="2")
        assert p.asset_exposure({"BTCUSDT": D("110")}) == {"BTCUSDT": D("220")}


class TestExcursions:
    def test_mae_and_mfe_track_the_worst_and_best_prices_seen(self):
        p = fresh()
        position = buy(p)
        position.observe(high=D("108"), low=D("97"))
        position.observe(high=D("104"), low=D("92"))
        assert position.mfe() == pytest.approx(D("0.08"))
        assert position.mae() == pytest.approx(D("-0.08"))
