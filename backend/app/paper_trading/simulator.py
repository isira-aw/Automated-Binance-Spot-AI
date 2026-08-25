"""Paper trading simulator (§11B).

Uses real market data and simulates orders, fills, fees, slippage, latency,
partial fills, balances, positions and P&L (§83). This is the primary Tier 1
validation tool: a strategy that cannot survive here has no business reaching
a real order book.

Every entry routes through the risk engine (§31). :meth:`PaperTradingEngine.
open_position` cannot be called with anything other than an APPROVED
:class:`RiskAssessment`, and it re-checks that on entry rather than trusting
the caller -- the risk engine's authority has to hold even against a bug in
this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig
from app.core.logging_config import get_logger
from app.models.enums import OrderSide, RiskDecision
from app.paper_trading.fills import (
    exit_reason_for_bar,
    simulate_fill,
    update_trailing_stop,
)
from app.paper_trading.portfolio import ClosedTrade, OpenPosition, Portfolio
from app.risk.engine import AccountState, RiskAssessment, RiskEngine, SystemState, TradeRequest

logger = get_logger("paper_trading.simulator")


@dataclass
class Bar:
    """One closed candle the simulator steps through."""

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass
class SimulatorConfig:
    fee_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal("5")
    allow_partial_fills: bool = True


class PaperTradingEngine:
    """Simulated venue over a real portfolio and the real risk engine."""

    VENUE = "PAPER"

    def __init__(
        self,
        *,
        portfolio: Portfolio,
        risk_engine: RiskEngine,
        config: SimulatorConfig | None = None,
    ) -> None:
        self.portfolio = portfolio
        self.risk = risk_engine
        self.config = config or SimulatorConfig()
        self.rejected_count = 0
        self._last_exit_time: dict[str, datetime] = {}

    # -- risk-engine plumbing -------------------------------------------

    def account_state(self, prices: dict[str, Decimal]) -> AccountState:
        """Translate the portfolio into what the risk engine needs (§31)."""
        portfolio = self.portfolio
        return AccountState(
            equity=portfolio.equity(prices),
            available_quote=portfolio.quote_balance,
            peak_equity=portfolio.peak_equity,
            realised_pnl_today=portfolio.realised_pnl,
            unrealised_pnl=portfolio.unrealised_pnl(prices),
            consecutive_losses=portfolio.consecutive_losses,
            open_positions=len(portfolio.positions),
            asset_exposure=portfolio.asset_exposure(prices),
        )

    def seconds_since_last_exit(self, symbol: str, now: datetime) -> int | None:
        last = self._last_exit_time.get(symbol)
        return None if last is None else int((now - last).total_seconds())

    def evaluate_entry(
        self,
        *,
        symbol: str,
        entry_price: Decimal,
        stop_price: Decimal | None,
        filters: SymbolFilters,
        prices: dict[str, Decimal],
        now: datetime,
        system: SystemState | None = None,
        spread_fraction: Decimal | None = None,
        atr_fraction: Decimal | None = None,
        signal_id: int | None = None,
    ) -> RiskAssessment:
        """Ask the risk engine whether this entry is permitted, and how big."""
        request = TradeRequest(
            symbol=symbol,
            entry_price=entry_price,
            stop_price=stop_price,
            filters=filters,
            taker_fee=self.config.fee_rate,
            spread_fraction=spread_fraction,
            atr_fraction=atr_fraction,
            seconds_since_last_exit=self.seconds_since_last_exit(symbol, now),
            signal_id=signal_id,
        )
        assessment = self.risk.evaluate(
            request, self.account_state(prices), system or SystemState()
        )
        if not assessment.approved:
            self.rejected_count += 1
        return assessment

    # -- execution ------------------------------------------------------

    def open_position(
        self,
        *,
        assessment: RiskAssessment,
        symbol: str,
        reference_price: Decimal,
        timestamp: datetime,
        filters: SymbolFilters,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        trailing_distance: Decimal | None = None,
        available_liquidity: Decimal | None = None,
        signal_id: int | None = None,
    ) -> OpenPosition | None:
        """Open a position from an APPROVED assessment.

        Re-validates the assessment rather than trusting the caller: the risk
        engine is the highest authority (§31), and that must hold even if a
        bug elsewhere in this module passes the wrong object.
        """
        if assessment.decision is not RiskDecision.APPROVED or assessment.size is None:
            raise ValueError(
                "open_position requires an APPROVED risk assessment; "
                f"got {assessment.decision.value} ({assessment.rule})."
            )

        fill = simulate_fill(
            requested_quantity=assessment.size.quantity,
            reference_price=reference_price,
            side=OrderSide.BUY,
            fee_rate=self.config.fee_rate,
            slippage_bps=self.config.slippage_bps,
            available_liquidity=available_liquidity if self.config.allow_partial_fills else None,
            step_size=filters.step_size,
        )
        if fill.is_empty:
            return None

        position = self.portfolio.open_position(
            symbol=symbol,
            quantity=fill.filled_quantity,
            price=fill.average_price,
            fee=fill.fee,
            timestamp=timestamp,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_distance=trailing_distance,
            signal_id=signal_id,
        )
        logger.info(
            "Paper position opened",
            extra={
                "event_type": "paper_position_opened",
                "symbol": symbol,
                "quantity": str(fill.filled_quantity),
                "price": str(fill.average_price),
                "partial": fill.is_partial,
            },
        )
        return position

    def close_position(
        self,
        *,
        symbol: str,
        reference_price: Decimal,
        timestamp: datetime,
        reason: str,
        filters: SymbolFilters | None = None,
    ) -> ClosedTrade | None:
        position = self.portfolio.positions.get(symbol)
        if position is None:
            return None

        fill = simulate_fill(
            requested_quantity=position.quantity,
            reference_price=reference_price,
            side=OrderSide.SELL,
            fee_rate=self.config.fee_rate,
            slippage_bps=self.config.slippage_bps,
            # An exit is never partially filled by choice: leaving a remnant
            # open because the book was thin is a position-management
            # decision, not something to bury in the fill model.
            available_liquidity=None,
            step_size=filters.step_size if filters else None,
        )
        if fill.is_empty:
            return None

        trade = self.portfolio.close_position(
            symbol=symbol,
            price=fill.average_price,
            fee=fill.fee,
            slippage_cost=fill.slippage_cost,
            timestamp=timestamp,
            reason=reason,
        )
        self._last_exit_time[symbol] = timestamp
        logger.info(
            "Paper position closed",
            extra={
                "event_type": "paper_position_closed",
                "symbol": symbol,
                "reason": reason,
                "net_pnl": str(trade.net_pnl),
            },
        )
        return trade

    # -- per-bar monitoring ---------------------------------------------

    def process_bar(self, bar: Bar, *, filters: SymbolFilters | None = None) -> ClosedTrade | None:
        """Advance one candle: update excursions, trail the stop, check exits.

        Exits fill at the stop/target price rather than the bar's close: a
        stop that only triggers at the close is not a stop, and would
        understate losses on every gap (§82's unrealistic-fills audit).

        Order of operations matters and is deliberately pessimistic. The exit
        is tested against the stop **as it stood entering this bar**, and the
        trailing stop is ratcheted only afterwards, for subsequent bars.
        Ratcheting first would test the bar's low against a stop raised by
        that same bar's high -- silently assuming the high came first and
        handing the trade a better exit than the data can justify. Intrabar
        order is unknowable from OHLC (§82), so the assumption that cannot
        flatter results is the only one available.
        """
        position = self.portfolio.positions.get(bar.symbol)
        if position is None:
            self.portfolio.update_peak_equity({bar.symbol: bar.close})
            return None

        position.observe(bar.high, bar.low)

        reason = exit_reason_for_bar(
            high=bar.high,
            low=bar.low,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
        )
        if reason is None:
            # Only a bar that did not exit ratchets the trail forward.
            position.stop_loss = update_trailing_stop(
                current_stop=position.stop_loss,
                high=bar.high,
                trailing_distance=position.trailing_distance,
            )
            self.portfolio.update_peak_equity({bar.symbol: bar.close})
            return None

        exit_price = position.stop_loss if reason == "STOP_LOSS" else position.take_profit
        assert exit_price is not None  # exit_reason_for_bar only fires when set
        trade = self.close_position(
            symbol=bar.symbol,
            reference_price=exit_price,
            timestamp=bar.timestamp,
            reason=reason,
            filters=filters,
        )
        self.portfolio.update_peak_equity({bar.symbol: bar.close})
        return trade

    def force_close_all(
        self, prices: dict[str, Decimal], timestamp: datetime, *, reason: str = "FORCED_EXIT"
    ) -> list[ClosedTrade]:
        """Close every open position, e.g. at the end of a backtest window."""
        closed: list[ClosedTrade] = []
        for symbol in list(self.portfolio.positions):
            position = self.portfolio.positions[symbol]
            trade = self.close_position(
                symbol=symbol,
                reference_price=prices.get(symbol, position.entry_price),
                timestamp=timestamp,
                reason=reason,
            )
            if trade is not None:
                closed.append(trade)
        return closed


def build_engine(
    *,
    initial_balance: Decimal,
    risk: RiskConfig,
    fee_rate: Decimal,
    slippage_bps: Decimal,
    allow_partial_fills: bool = True,
) -> PaperTradingEngine:
    """Construct a simulator with a fresh portfolio at ``initial_balance``."""
    return PaperTradingEngine(
        portfolio=Portfolio(quote_balance=initial_balance, initial_balance=initial_balance),
        risk_engine=RiskEngine(risk),
        config=SimulatorConfig(
            fee_rate=fee_rate, slippage_bps=slippage_bps, allow_partial_fills=allow_partial_fills
        ),
    )
