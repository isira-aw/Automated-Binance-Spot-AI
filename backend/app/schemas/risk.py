"""Schemas for the risk namespace (§31, §59)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RiskParametersOut(BaseModel):
    """The active limits, read-only.

    Changing a risk parameter is a Settings concern, never something the risk
    namespace itself offers -- the engine enforces limits, it does not own
    their values (§31).
    """

    max_risk_per_trade: float
    max_position_size: float
    max_asset_exposure: float
    max_portfolio_exposure: float
    max_simultaneous_positions: int
    max_daily_loss: float
    max_drawdown: float
    max_consecutive_losses: int
    max_slippage: float
    spread_protection: float
    volatility_protection: float
    stale_data_protection_seconds: int
    api_failure_protection_threshold: int
    model_health_protection: bool
    cooldown_period_seconds: int


class RiskEventOut(BaseModel):
    id: int
    timestamp: datetime
    venue: str
    symbol: str | None
    decision: str
    rule: str
    reason: str
    details: dict[str, Any] | None


class RiskStateOut(BaseModel):
    """Whether trading is currently permitted, and why not if it is not."""

    trading_permitted: bool
    decision: str
    rule: str | None
    reason: str | None
    engine_state: str
    checked_at: datetime
