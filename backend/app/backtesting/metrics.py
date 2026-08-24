"""Trading performance metrics (§41).

One definition per metric, used by backtests, paper trading and (later) live
reporting alike -- §41 exists precisely so these do not get redefined per
surface and quietly disagree.

Every metric is computed from **net** P&L: fees and slippage are already
deducted by the portfolio (§87). A "profit factor" computed gross would be a
different, flattering number.

Win rate is reported but never treated as the objective (§1, §41): a strategy
that wins 95% of the time and gives it all back on the 5% is not a good
strategy, which is why expectancy, profit factor and drawdown sit alongside it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import pairwise

from app.paper_trading.portfolio import ClosedTrade

# Bars per year, used to annualise Sharpe/Sortino per timeframe. Crypto trades
# 24/7, so there is no trading-day convention to apply -- these are simply
# how many candles of each size fit in a calendar year.
BARS_PER_YEAR = {
    "15m": 365 * 24 * 4,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}


@dataclass
class PerformanceMetrics:
    """The §41 metric set. Values are ``None`` when undefined, never faked."""

    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float | None = None
    loss_rate: float | None = None
    gross_pnl: Decimal = Decimal(0)
    net_pnl: Decimal = Decimal(0)
    total_fees: Decimal = Decimal(0)
    total_slippage: Decimal = Decimal(0)
    average_trade: Decimal | None = None
    average_win: Decimal | None = None
    average_loss: Decimal | None = None
    expectancy: Decimal | None = None
    profit_factor: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float | None = None
    return_pct: float | None = None
    exposure: float | None = None
    equity_curve: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": self.win_rate,
            "loss_rate": self.loss_rate,
            "gross_pnl": float(self.gross_pnl),
            "net_pnl": float(self.net_pnl),
            "total_fees": float(self.total_fees),
            "total_slippage": float(self.total_slippage),
            "average_trade": float(self.average_trade) if self.average_trade is not None else None,
            "average_win": float(self.average_win) if self.average_win is not None else None,
            "average_loss": float(self.average_loss) if self.average_loss is not None else None,
            "expectancy": float(self.expectancy) if self.expectancy is not None else None,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "return_pct": self.return_pct,
            "exposure": self.exposure,
        }


def max_drawdown(equity_curve: list[Decimal]) -> float | None:
    """Largest peak-to-trough decline as a positive fraction."""
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0]
    worst = Decimal(0)
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return float(worst)


def _returns_from_equity(equity_curve: list[Decimal]) -> list[float]:
    returns = []
    for previous, current in pairwise(equity_curve):
        if previous > 0:
            returns.append(float((current - previous) / previous))
    return returns


def sharpe_ratio(equity_curve: list[Decimal], *, periods_per_year: int) -> float | None:
    """Annualised Sharpe of the equity curve, or None if undefined.

    Risk-free rate is taken as zero: the alternative is picking a rate, and a
    wrong assumed rate silently shifts every comparison between strategies.
    """
    returns = _returns_from_equity(equity_curve)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    stdev = math.sqrt(variance)
    if stdev == 0:
        # A perfectly flat curve has no risk-adjusted return to speak of.
        return None
    return (mean / stdev) * math.sqrt(periods_per_year)


def sortino_ratio(equity_curve: list[Decimal], *, periods_per_year: int) -> float | None:
    """Like Sharpe but penalising only downside deviation."""
    returns = _returns_from_equity(equity_curve)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    downside = [r for r in returns if r < 0]
    if not downside:
        # No losing period at all: Sortino is undefined rather than infinite.
        return None
    downside_variance = sum(r**2 for r in downside) / len(downside)
    downside_dev = math.sqrt(downside_variance)
    if downside_dev == 0:
        return None
    return (mean / downside_dev) * math.sqrt(periods_per_year)


def compute_metrics(
    trades: list[ClosedTrade],
    equity_curve: list[Decimal],
    *,
    initial_capital: Decimal,
    timeframe: str = "1h",
    bars_in_market: int = 0,
    total_bars: int = 0,
) -> PerformanceMetrics:
    """Compute the full §41 metric set from closed trades and an equity curve."""
    metrics = PerformanceMetrics(equity_curve=[float(value) for value in equity_curve])
    metrics.trade_count = len(trades)

    if trades:
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        metrics.win_count = len(wins)
        metrics.loss_count = len(losses)
        metrics.win_rate = len(wins) / len(trades)
        metrics.loss_rate = len(losses) / len(trades)

        metrics.gross_pnl = sum((t.gross_pnl for t in trades), Decimal(0))
        metrics.net_pnl = sum((t.net_pnl for t in trades), Decimal(0))
        metrics.total_fees = sum((t.fees for t in trades), Decimal(0))
        metrics.total_slippage = sum((t.slippage_cost for t in trades), Decimal(0))

        metrics.average_trade = metrics.net_pnl / len(trades)
        if wins:
            metrics.average_win = sum((t.net_pnl for t in wins), Decimal(0)) / len(wins)
        if losses:
            metrics.average_loss = sum((t.net_pnl for t in losses), Decimal(0)) / len(losses)

        # Expectancy: the average outcome per trade, which is average_trade --
        # stated explicitly because it is the number that decides whether a
        # strategy is worth running at all (§41).
        metrics.expectancy = metrics.average_trade

        gross_profit = sum((t.net_pnl for t in wins), Decimal(0))
        gross_loss = -sum((t.net_pnl for t in losses), Decimal(0))
        if gross_loss > 0:
            metrics.profit_factor = float(gross_profit / gross_loss)
        elif gross_profit > 0:
            # No losses at all: profit factor is undefined (division by zero),
            # not infinity, and reporting a number here would be a fabrication.
            metrics.profit_factor = None

    if equity_curve:
        metrics.max_drawdown = max_drawdown(equity_curve)
        periods = BARS_PER_YEAR.get(timeframe, BARS_PER_YEAR["1h"])
        metrics.sharpe_ratio = sharpe_ratio(equity_curve, periods_per_year=periods)
        metrics.sortino_ratio = sortino_ratio(equity_curve, periods_per_year=periods)
        if initial_capital > 0:
            metrics.return_pct = float((equity_curve[-1] - initial_capital) / initial_capital)

    if total_bars > 0:
        metrics.exposure = bars_in_market / total_bars

    return metrics
