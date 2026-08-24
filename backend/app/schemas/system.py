"""Schemas for the system and settings endpoints."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ComponentHealth, EngineState


class ComponentStatusOut(BaseModel):
    status: ComponentHealth
    detail: str | None = None


class HealthOut(BaseModel):
    """Response of ``GET /api/v1/system/health`` (§105)."""

    overall: ComponentHealth
    checked_at: str
    components: dict[str, dict[str, Any]]


class VersionOut(BaseModel):
    app_name: str
    api_version: str = "v1"
    environment: str
    strategy_version: str
    feature_version: str
    schema_revision: str | None = None


class TierStatusOut(BaseModel):
    """Which capability tier each subsystem currently runs at (§1a, §14).

    The UI uses this to label Tier 2 surfaces as shadow/research rather than
    letting the user assume they influence live decisions.
    """

    tier1_components: list[str]
    tier2_components: list[str]
    tier2_enabled: dict[str, bool]
    influencing_signals: list[str]


class SystemStateOut(BaseModel):
    """Persisted runtime state (§89)."""

    mode: Literal["BACKTEST", "PAPER", "BINANCE_TESTNET", "LIVE"]
    engine_state: EngineState
    live_armed: bool
    live_trading_enabled: bool
    last_shutdown_at: str | None = None
    model_registry_ok: bool
    model_registry_problems: list[dict[str, str]] = Field(default_factory=list)


class RiskConfigOut(BaseModel):
    """Read-only view of the authoritative risk limits (§31)."""

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


class TradingSettingsOut(BaseModel):
    assets: list[str]
    timeframes: list[str]
    decision_timeframe: str
    entry_timeframe: str
    mode: str
    live_trading_enabled: bool
    minimum_confidence: float
    maker_fee: float
    taker_fee: float


class SettingsOut(BaseModel):
    """Non-secret configuration exposed to the frontend (§60, §98).

    Credentials are never included — only whether they are configured.
    """

    environment: str
    trading: TradingSettingsOut
    risk: RiskConfigOut
    paper_trading: dict[str, Any]
    backtesting: dict[str, Any]
    models: dict[str, Any]
    binance: dict[str, Any]
    tiers: TierStatusOut
