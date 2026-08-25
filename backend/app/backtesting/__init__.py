"""Event-driven backtesting (§35), reusing the paper trading components."""

from app.backtesting.engine import (
    BacktestAssumptions,
    BacktestEngine,
    BacktestResult,
    HistoricalBar,
    StrategyDecision,
)
from app.backtesting.metrics import PerformanceMetrics, compute_metrics

__all__ = [
    "BacktestAssumptions",
    "BacktestEngine",
    "BacktestResult",
    "HistoricalBar",
    "PerformanceMetrics",
    "StrategyDecision",
    "compute_metrics",
]
