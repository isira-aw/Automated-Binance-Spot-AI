"""Internal paper trading simulator (§11B) — the primary Tier 1 validation tool."""

from app.paper_trading.fills import FillResult, simulate_fill
from app.paper_trading.portfolio import ClosedTrade, OpenPosition, Portfolio
from app.paper_trading.simulator import (
    Bar,
    PaperTradingEngine,
    SimulatorConfig,
    build_engine,
)

__all__ = [
    "Bar",
    "ClosedTrade",
    "FillResult",
    "OpenPosition",
    "PaperTradingEngine",
    "Portfolio",
    "SimulatorConfig",
    "build_engine",
    "simulate_fill",
]
