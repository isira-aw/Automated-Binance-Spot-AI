"""Event-driven backtesting engine (§35, §82).

Steps bar by bar through history, reusing the **same** risk engine, position
sizing, fill model and portfolio accounting that paper trading uses (§35: "a
materially different backtest strategy is a bug, not a shortcut"). Nothing in
this module reimplements execution -- it drives :class:`PaperTradingEngine`
over historical bars instead of live ones.

The two structural guarantees that make a result meaningful:

1. **No future data.** At bar *i* the strategy is handed bars ``[0..i]`` only.
   The engine never passes the full series to a strategy callback, so a
   strategy *cannot* peek ahead even by accident -- that is enforced by the
   call signature rather than by asking strategies to behave.
2. **Costs always applied.** Fees and slippage come from the shared fill
   model, which has no zero-cost path (§87).

Every run records its assumptions (§82) so a result without the audit trail
cannot be mistaken for a validated one.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.backtesting.metrics import PerformanceMetrics, compute_metrics
from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig
from app.core.logging_config import get_logger
from app.paper_trading.portfolio import ClosedTrade
from app.paper_trading.simulator import Bar, PaperTradingEngine, build_engine
from app.risk.engine import SystemState

logger = get_logger("backtesting.engine")


@dataclass(frozen=True)
class HistoricalBar:
    """One closed candle from history."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal(0)


@dataclass(frozen=True)
class StrategyDecision:
    """What a strategy wants to do at the current bar.

    ``None`` from a strategy means WAIT, which is a first-class outcome (§54)
    and by far the most common one -- the system prefers no trade to a
    low-quality one.
    """

    action: str  # "BUY" or "EXIT"
    stop_price: Decimal | None = None
    take_profit: Decimal | None = None
    trailing_distance: Decimal | None = None
    reason: str = ""


# A strategy sees only history up to and including the current bar.
StrategyFn = Callable[[Sequence[HistoricalBar]], StrategyDecision | None]


@dataclass
class BacktestAssumptions:
    """The §82 disclosure set. A run without these is not a meaningful result."""

    fee_model: str
    slippage_model: str
    fill_model: str
    lookahead_prevention: str
    intrabar_assumption: str
    liquidity_assumption: str
    survivorship_note: str

    def to_dict(self) -> dict[str, str]:
        return {
            "fee_model": self.fee_model,
            "slippage_model": self.slippage_model,
            "fill_model": self.fill_model,
            "lookahead_prevention": self.lookahead_prevention,
            "intrabar_assumption": self.intrabar_assumption,
            "liquidity_assumption": self.liquidity_assumption,
            "survivorship_note": self.survivorship_note,
        }


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    initial_capital: Decimal
    final_equity: Decimal
    trades: list[ClosedTrade]
    metrics: PerformanceMetrics
    assumptions: BacktestAssumptions
    bars_processed: int = 0
    risk_rejections: int = 0
    equity_curve: list[Decimal] = field(default_factory=list)


def default_assumptions(*, fee_rate: Decimal, slippage_bps: Decimal) -> BacktestAssumptions:
    return BacktestAssumptions(
        fee_model=f"Taker fee of {fee_rate} applied to both entry and exit notional.",
        slippage_model=(
            f"{slippage_bps} bps applied against the trader on every fill "
            "(buys fill higher, sells fill lower). Never favourable."
        ),
        fill_model=(
            "Market fills at the reference price adjusted for slippage. Stops "
            "and targets fill at their trigger price, not the bar close."
        ),
        lookahead_prevention=(
            "The strategy callback receives bars[0..i] only; the full series is "
            "never passed, so a strategy cannot read a future bar even by accident."
        ),
        intrabar_assumption=(
            "When a bar's range spans both stop and target, the STOP is taken. "
            "Intrabar order is unknowable from OHLC, so the assumption that "
            "cannot flatter results is used."
        ),
        liquidity_assumption=(
            "Full fills assumed; no partial-fill modelling from order-book depth. "
            "Reasonable for BTC/ETH/BNB majors at this account size, and stated "
            "explicitly because it would not hold for a thin book."
        ),
        survivorship_note=(
            "Single-symbol backtest over a fixed symbol chosen in advance; no "
            "universe selection, so no survivorship bias is introduced here."
        ),
    )


class BacktestEngine:
    """Drives the paper trading engine over historical bars."""

    def __init__(
        self,
        *,
        symbol: str,
        timeframe: str,
        initial_capital: Decimal,
        risk: RiskConfig,
        fee_rate: Decimal,
        slippage_bps: Decimal,
        filters: SymbolFilters,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage_bps = slippage_bps
        self.filters = filters
        self.engine: PaperTradingEngine = build_engine(
            initial_balance=initial_capital,
            risk=risk,
            fee_rate=fee_rate,
            slippage_bps=slippage_bps,
            # Historical OHLC carries no depth information, so modelling
            # partial fills from it would be inventing data (§82).
            allow_partial_fills=False,
        )

    def run(self, bars: Sequence[HistoricalBar], strategy: StrategyFn) -> BacktestResult:
        """Replay ``bars`` in order, asking ``strategy`` what to do at each one."""
        if not bars:
            raise ValueError("A backtest needs at least one bar.")

        equity_curve: list[Decimal] = []
        bars_in_market = 0

        for index, bar in enumerate(bars):
            simulator_bar = Bar(
                symbol=self.symbol,
                timestamp=bar.timestamp,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
            )

            # 1. Resolve exits on this bar before considering any new entry:
            #    a position that stopped out this bar must not still be
            #    counted as open when sizing the next one.
            self.engine.process_bar(simulator_bar, filters=self.filters)

            # 2. Ask the strategy, handing it history up to *this* bar only.
            decision = strategy(bars[: index + 1])

            if decision is not None:
                self._apply(decision, bar)

            if self.symbol in self.engine.portfolio.positions:
                bars_in_market += 1

            prices = {self.symbol: bar.close}
            self.engine.portfolio.update_peak_equity(prices)
            equity_curve.append(self.engine.portfolio.equity(prices))

        # Close anything still open at the end of the window, so the result
        # reflects realised outcomes rather than an open position's paper gain.
        final_bar = bars[-1]
        self.engine.force_close_all(
            {self.symbol: final_bar.close}, final_bar.timestamp, reason="BACKTEST_END"
        )
        final_prices = {self.symbol: final_bar.close}
        final_equity = self.engine.portfolio.equity(final_prices)
        if equity_curve:
            equity_curve[-1] = final_equity

        metrics = compute_metrics(
            self.engine.portfolio.closed_trades,
            equity_curve,
            initial_capital=self.initial_capital,
            timeframe=self.timeframe,
            bars_in_market=bars_in_market,
            total_bars=len(bars),
        )

        logger.info(
            "Backtest complete",
            extra={
                "event_type": "backtest_complete",
                "symbol": self.symbol,
                "bars": len(bars),
                "trades": metrics.trade_count,
                "net_pnl": str(metrics.net_pnl),
            },
        )

        return BacktestResult(
            symbol=self.symbol,
            timeframe=self.timeframe,
            initial_capital=self.initial_capital,
            final_equity=final_equity,
            trades=list(self.engine.portfolio.closed_trades),
            metrics=metrics,
            assumptions=default_assumptions(
                fee_rate=self.fee_rate, slippage_bps=self.slippage_bps
            ),
            bars_processed=len(bars),
            risk_rejections=self.engine.rejected_count,
            equity_curve=equity_curve,
        )

    def _apply(self, decision: StrategyDecision, bar: HistoricalBar) -> None:
        """Act on a strategy decision, always through the risk engine (§31)."""
        holding = self.symbol in self.engine.portfolio.positions

        if decision.action == "EXIT" and holding:
            self.engine.close_position(
                symbol=self.symbol,
                reference_price=bar.close,
                timestamp=bar.timestamp,
                reason=decision.reason or "STRATEGY_EXIT",
                filters=self.filters,
            )
            return

        if decision.action != "BUY" or holding:
            return

        prices = {self.symbol: bar.close}
        assessment = self.engine.evaluate_entry(
            symbol=self.symbol,
            entry_price=bar.close,
            stop_price=decision.stop_price,
            filters=self.filters,
            prices=prices,
            now=bar.timestamp,
            system=SystemState(),
        )
        if not assessment.approved:
            return

        self.engine.open_position(
            assessment=assessment,
            symbol=self.symbol,
            reference_price=bar.close,
            timestamp=bar.timestamp,
            filters=self.filters,
            stop_loss=decision.stop_price,
            take_profit=decision.take_profit,
            trailing_distance=decision.trailing_distance,
        )
