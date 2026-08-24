"""Risk parameters — the single source of truth (MASTER PROMPT §31).

Every other part of the system (frontend controls, position sizing, order
validation, strategy config) references this model.  Risk parameters are
never redefined elsewhere; doing so lets definitions drift apart, and a
drifting risk limit is a silent weakening of the safety layer.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RiskConfig(BaseModel):
    """Authoritative risk limits.

    Fractions are expressed as decimals in [0, 1] (0.01 == 1%).
    Monetary values are quote-currency (USDT) amounts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Exposure and sizing ---------------------------------------------
    max_risk_per_trade: Decimal = Field(
        default=Decimal("0.01"),
        gt=0,
        le=1,
        description="Fraction of account equity risked on a single trade.",
    )
    max_position_size: Decimal = Field(
        default=Decimal("0.35"),
        gt=0,
        le=1,
        description="Max fraction of equity a single position may occupy.",
    )
    max_asset_exposure: Decimal = Field(
        default=Decimal("0.50"),
        gt=0,
        le=1,
        description="Max fraction of equity exposed to one asset.",
    )
    max_portfolio_exposure: Decimal = Field(
        default=Decimal("0.80"),
        gt=0,
        le=1,
        description="Max fraction of equity deployed across all positions.",
    )
    max_simultaneous_positions: int = Field(
        default=1,
        ge=1,
        description=(
            "At <$50 account size, concentration in the single best "
            "opportunity is the default (§55)."
        ),
    )

    # --- Loss limits ------------------------------------------------------
    max_daily_loss: Decimal = Field(
        default=Decimal("0.03"),
        gt=0,
        le=1,
        description="Daily realised+unrealised loss fraction that pauses trading.",
    )
    max_drawdown: Decimal = Field(
        default=Decimal("0.15"),
        gt=0,
        le=1,
        description="Peak-to-trough equity drawdown that pauses trading.",
    )
    max_consecutive_losses: int = Field(
        default=4,
        ge=1,
        description="Consecutive losing trades before a cooldown is enforced.",
    )

    # --- Execution quality protections ------------------------------------
    max_slippage: Decimal = Field(
        default=Decimal("0.002"),
        ge=0,
        le=1,
        description="Max tolerated slippage fraction vs. signal price.",
    )
    spread_protection: Decimal = Field(
        default=Decimal("0.001"),
        ge=0,
        le=1,
        description="Reject entries when the bid/ask spread fraction exceeds this.",
    )
    volatility_protection: Decimal = Field(
        default=Decimal("0.08"),
        ge=0,
        description="Reject entries when ATR/price exceeds this fraction.",
    )

    # --- Data / system health protections ---------------------------------
    stale_data_protection_seconds: int = Field(
        default=120,
        ge=1,
        description="Market data older than this is stale; never trade on it.",
    )
    api_failure_protection_threshold: int = Field(
        default=5,
        ge=1,
        description="Consecutive exchange API failures before trading pauses.",
    )
    model_health_protection: bool = Field(
        default=True,
        description="Block trading when the active model reports unhealthy.",
    )

    # --- Timing -----------------------------------------------------------
    cooldown_period_seconds: int = Field(
        default=900,
        ge=0,
        description="Minimum wait after an exit (or a loss streak) per symbol.",
    )


DEFAULT_RISK_CONFIG = RiskConfig()
