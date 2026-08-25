"""The risk engine — the highest-authority component (§31).

No model, no LLM, no frontend request and no strategy config may bypass this.
Every decision returns ``APPROVED | REJECTED | PAUSED`` with a human-readable
explanation the frontend surfaces verbatim (§101).

Rule ordering matters and is deliberate:

1. **Account-level halts first** (emergency stop, daily loss, drawdown, loss
   streak). These produce ``PAUSED`` -- the account itself is out of action,
   and no per-trade detail could change that.
2. **System-health gates next** (stale data, API failures, model health).
   Also ``PAUSED``: the system cannot currently be trusted to evaluate a
   trade, which is different from having evaluated one and said no.
3. **Per-trade checks last** (spread, volatility, cooldown, exposure,
   sizing). These produce ``REJECTED`` -- this specific trade is not allowed,
   another one might be.

Evaluating in the other order would let a per-trade rejection mask an
account-level halt, which would read to an operator as "that one trade was
bad" when the truth is "trading is stopped".

Every parameter comes from :class:`RiskConfig` (§31's single source of truth).
This module enforces limits; it never defines them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig
from app.core.logging_config import get_logger
from app.core.time_utils import utc_now
from app.models.enums import EngineState, RiskDecision
from app.risk.position_sizing import PositionSize, calculate_position_size

logger = get_logger("risk.engine")

# --- Reason codes (stable strings; the frontend maps these to copy) -------
RULE_EMERGENCY_STOP = "emergency_stop"
RULE_ENGINE_PAUSED = "engine_paused"
RULE_MAX_DAILY_LOSS = "max_daily_loss"
RULE_MAX_DRAWDOWN = "max_drawdown"
RULE_MAX_CONSECUTIVE_LOSSES = "max_consecutive_losses"
RULE_STALE_DATA = "stale_data_protection"
RULE_API_FAILURE = "api_failure_protection"
RULE_MODEL_HEALTH = "model_health_protection"
RULE_SPREAD = "spread_protection"
RULE_VOLATILITY = "volatility_protection"
RULE_COOLDOWN = "cooldown_period"
RULE_MAX_POSITIONS = "max_simultaneous_positions"
RULE_ASSET_EXPOSURE = "max_asset_exposure"
RULE_PORTFOLIO_EXPOSURE = "max_portfolio_exposure"
RULE_POSITION_SIZE = "position_sizing"
RULE_SLIPPAGE = "max_slippage"
RULE_APPROVED = "approved"


@dataclass
class AccountState:
    """Everything the account-level rules need, in quote currency."""

    equity: Decimal
    available_quote: Decimal
    peak_equity: Decimal
    realised_pnl_today: Decimal = Decimal(0)
    unrealised_pnl: Decimal = Decimal(0)
    consecutive_losses: int = 0
    open_positions: int = 0
    asset_exposure: dict[str, Decimal] = field(default_factory=dict)

    @property
    def total_exposure(self) -> Decimal:
        return sum(self.asset_exposure.values(), Decimal(0))

    @property
    def drawdown_fraction(self) -> Decimal:
        """Peak-to-trough drawdown as a positive fraction of peak equity."""
        if self.peak_equity <= 0:
            return Decimal(0)
        drop = self.peak_equity - self.equity
        return max(Decimal(0), drop / self.peak_equity)

    @property
    def daily_loss_fraction(self) -> Decimal:
        """Today's loss as a positive fraction of equity, 0 if up on the day.

        Includes unrealised P&L: a position that is deeply underwater has
        already lost the money, whether or not it has been closed.
        """
        if self.equity <= 0:
            return Decimal(1)
        combined = self.realised_pnl_today + self.unrealised_pnl
        if combined >= 0:
            return Decimal(0)
        return -combined / self.equity


@dataclass
class SystemState:
    """Health inputs the risk engine gates on (§44)."""

    engine_state: EngineState = EngineState.RUNNING
    market_data_stale: bool = False
    consecutive_api_failures: int = 0
    model_healthy: bool = True
    last_market_data_at: datetime | None = None


@dataclass
class TradeRequest:
    """A proposed entry, before any of it is allowed to become an order."""

    symbol: str
    entry_price: Decimal
    stop_price: Decimal | None
    filters: SymbolFilters
    taker_fee: Decimal
    spread_fraction: Decimal | None = None
    atr_fraction: Decimal | None = None
    seconds_since_last_exit: int | None = None
    expected_slippage: Decimal | None = None
    signal_id: int | None = None


@dataclass
class RiskAssessment:
    """The engine's verdict, with everything needed to explain and audit it."""

    decision: RiskDecision
    rule: str
    reason: str
    size: PositionSize | None = None
    details: dict[str, str] = field(default_factory=dict)
    assessed_at: datetime = field(default_factory=utc_now)

    @property
    def approved(self) -> bool:
        return self.decision is RiskDecision.APPROVED

    @classmethod
    def paused(cls, rule: str, reason: str, **details: object) -> RiskAssessment:
        return cls(
            decision=RiskDecision.PAUSED,
            rule=rule,
            reason=reason,
            details={k: str(v) for k, v in details.items()},
        )

    @classmethod
    def rejected(cls, rule: str, reason: str, **details: object) -> RiskAssessment:
        return cls(
            decision=RiskDecision.REJECTED,
            rule=rule,
            reason=reason,
            details={k: str(v) for k, v in details.items()},
        )


class RiskEngine:
    """Evaluates a proposed trade against every §31 limit."""

    def __init__(self, risk: RiskConfig) -> None:
        self._risk = risk

    @property
    def config(self) -> RiskConfig:
        return self._risk

    # -- account/system halts ------------------------------------------

    def check_account_halts(self, account: AccountState) -> RiskAssessment | None:
        """Account-level conditions that stop *all* trading, or None if clear."""
        risk = self._risk

        if account.daily_loss_fraction >= risk.max_daily_loss:
            return RiskAssessment.paused(
                RULE_MAX_DAILY_LOSS,
                (
                    f"Daily loss limit reached: down "
                    f"{account.daily_loss_fraction:.2%} against a limit of "
                    f"{risk.max_daily_loss:.2%}. No new orders will be submitted."
                ),
                daily_loss_fraction=account.daily_loss_fraction,
                limit=risk.max_daily_loss,
            )

        if account.drawdown_fraction >= risk.max_drawdown:
            return RiskAssessment.paused(
                RULE_MAX_DRAWDOWN,
                (
                    f"Maximum drawdown reached: {account.drawdown_fraction:.2%} "
                    f"from peak equity against a limit of {risk.max_drawdown:.2%}."
                ),
                drawdown_fraction=account.drawdown_fraction,
                limit=risk.max_drawdown,
            )

        if account.consecutive_losses >= risk.max_consecutive_losses:
            return RiskAssessment.paused(
                RULE_MAX_CONSECUTIVE_LOSSES,
                (
                    f"{account.consecutive_losses} consecutive losing trades "
                    f"(limit {risk.max_consecutive_losses}); trading is paused for review."
                ),
                consecutive_losses=account.consecutive_losses,
                limit=risk.max_consecutive_losses,
            )
        return None

    def check_system_health(self, system: SystemState) -> RiskAssessment | None:
        """System conditions that make evaluating a trade untrustworthy."""
        risk = self._risk

        if system.engine_state is EngineState.EMERGENCY_STOP:
            return RiskAssessment.paused(
                RULE_EMERGENCY_STOP,
                "Emergency stop is active. No new orders will be submitted.",
            )
        if system.engine_state is EngineState.PAUSED:
            return RiskAssessment.paused(
                RULE_ENGINE_PAUSED, "The trading engine is paused. No new orders will be submitted."
            )
        if system.market_data_stale:
            return RiskAssessment.paused(
                RULE_STALE_DATA,
                (
                    "Market data is stale; trading on a price that may no longer "
                    "be real is never permitted."
                ),
                last_market_data_at=system.last_market_data_at,
                max_age_seconds=risk.stale_data_protection_seconds,
            )
        if system.consecutive_api_failures >= risk.api_failure_protection_threshold:
            return RiskAssessment.paused(
                RULE_API_FAILURE,
                (
                    f"{system.consecutive_api_failures} consecutive exchange API "
                    f"failures (threshold {risk.api_failure_protection_threshold}); "
                    "the exchange connection cannot be trusted right now."
                ),
                consecutive_api_failures=system.consecutive_api_failures,
            )
        if risk.model_health_protection and not system.model_healthy:
            return RiskAssessment.paused(
                RULE_MODEL_HEALTH,
                "The active model is unhealthy; predictions from it will not be traded on.",
            )
        return None

    # -- per-trade checks ----------------------------------------------

    def _check_trade_conditions(
        self, request: TradeRequest, account: AccountState
    ) -> RiskAssessment | None:
        risk = self._risk

        if request.spread_fraction is not None and request.spread_fraction > risk.spread_protection:
            return RiskAssessment.rejected(
                RULE_SPREAD,
                (
                    f"Bid/ask spread {request.spread_fraction:.4%} exceeds the "
                    f"limit of {risk.spread_protection:.4%}."
                ),
                spread_fraction=request.spread_fraction,
                limit=risk.spread_protection,
            )
        if request.atr_fraction is not None and request.atr_fraction > risk.volatility_protection:
            return RiskAssessment.rejected(
                RULE_VOLATILITY,
                (
                    f"Volatility (ATR/price {request.atr_fraction:.2%}) exceeds the "
                    f"limit of {risk.volatility_protection:.2%}."
                ),
                atr_fraction=request.atr_fraction,
                limit=risk.volatility_protection,
            )
        if (
            request.expected_slippage is not None
            and request.expected_slippage > risk.max_slippage
        ):
            return RiskAssessment.rejected(
                RULE_SLIPPAGE,
                (
                    f"Expected slippage {request.expected_slippage:.4%} exceeds the "
                    f"limit of {risk.max_slippage:.4%}."
                ),
                expected_slippage=request.expected_slippage,
                limit=risk.max_slippage,
            )
        if (
            request.seconds_since_last_exit is not None
            and request.seconds_since_last_exit < risk.cooldown_period_seconds
        ):
            remaining = risk.cooldown_period_seconds - request.seconds_since_last_exit
            return RiskAssessment.rejected(
                RULE_COOLDOWN,
                (
                    f"Cooldown after the last exit on {request.symbol} has "
                    f"{remaining}s remaining."
                ),
                remaining_seconds=remaining,
            )
        if account.open_positions >= risk.max_simultaneous_positions:
            return RiskAssessment.rejected(
                RULE_MAX_POSITIONS,
                (
                    f"Already holding {account.open_positions} position(s); the "
                    f"limit is {risk.max_simultaneous_positions}."
                ),
                open_positions=account.open_positions,
                limit=risk.max_simultaneous_positions,
            )

        asset_exposure = account.asset_exposure.get(request.symbol, Decimal(0))
        if account.equity > 0 and asset_exposure >= account.equity * risk.max_asset_exposure:
            return RiskAssessment.rejected(
                RULE_ASSET_EXPOSURE,
                (
                    f"Exposure to {request.symbol} already fills the "
                    f"{risk.max_asset_exposure:.0%} per-asset limit."
                ),
                asset_exposure=asset_exposure,
            )
        if (
            account.equity > 0
            and account.total_exposure >= account.equity * risk.max_portfolio_exposure
        ):
            return RiskAssessment.rejected(
                RULE_PORTFOLIO_EXPOSURE,
                (
                    f"Total exposure already fills the "
                    f"{risk.max_portfolio_exposure:.0%} portfolio limit."
                ),
                total_exposure=account.total_exposure,
            )
        return None

    # -- the single entry point ----------------------------------------

    def evaluate(
        self, request: TradeRequest, account: AccountState, system: SystemState
    ) -> RiskAssessment:
        """Evaluate a proposed entry. This is the only way to get APPROVED."""
        halt = self.check_system_health(system) or self.check_account_halts(account)
        if halt is not None:
            self._log(halt, request)
            return halt

        rejection = self._check_trade_conditions(request, account)
        if rejection is not None:
            self._log(rejection, request)
            return rejection

        size = calculate_position_size(
            equity=account.equity,
            available_quote=account.available_quote,
            entry_price=request.entry_price,
            stop_price=request.stop_price,
            risk=self._risk,
            filters=request.filters,
            taker_fee=request.taker_fee,
            current_asset_exposure=account.asset_exposure.get(request.symbol, Decimal(0)),
            current_portfolio_exposure=account.total_exposure,
        )
        if not size.approved:
            assessment = RiskAssessment(
                decision=RiskDecision.REJECTED,
                rule=RULE_POSITION_SIZE,
                reason=size.reason or "Position could not be sized.",
                size=size,
                details={"reason_code": size.reason_code or "", **(size.details or {})},
            )
            self._log(assessment, request)
            return assessment

        assessment = RiskAssessment(
            decision=RiskDecision.APPROVED,
            rule=RULE_APPROVED,
            reason=(
                f"Approved: {size.quantity} {request.symbol} "
                f"(notional {size.notional:.4f}, risking {size.risk_amount:.4f})."
            ),
            size=size,
        )
        self._log(assessment, request)
        return assessment

    def _log(self, assessment: RiskAssessment, request: TradeRequest) -> None:
        logger.info(
            "Risk decision",
            extra={
                "event_type": "risk_decision",
                "symbol": request.symbol,
                "decision": assessment.decision.value,
                "rule": assessment.rule,
            },
        )
