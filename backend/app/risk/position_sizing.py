"""Position sizing against exchange filters and risk limits (§32).

Sizing is deliberately conservative at every rounding step: quantity rounds
*down* to the exchange's step size, never up, so a rounding artefact can only
ever reduce risk below the cap and never nudge it above one.

``REJECT: TRADE_NOT_ECONOMIC`` is the expected, common outcome at a <$50
account (§88) -- it is a normal answer, not an error to suppress or work
around by forcing a smaller-than-legal order.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from app.binance.exchange_metadata import SymbolFilters
from app.config.risk_config import RiskConfig

# Reason codes, surfaced verbatim to the frontend (§101).
REJECT_NO_STOP_DISTANCE = "NO_STOP_DISTANCE"
REJECT_TRADE_NOT_ECONOMIC = "TRADE_NOT_ECONOMIC"
REJECT_BELOW_MIN_QTY = "BELOW_MIN_QTY"
REJECT_BELOW_MIN_NOTIONAL = "BELOW_MIN_NOTIONAL"
REJECT_INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
REJECT_NO_EQUITY = "NO_EQUITY"


@dataclass(frozen=True)
class PositionSize:
    """A sized order, or a rejection with the reason why."""

    approved: bool
    quantity: Decimal = Decimal(0)
    notional: Decimal = Decimal(0)
    risk_amount: Decimal = Decimal(0)
    estimated_fee: Decimal = Decimal(0)
    reason_code: str | None = None
    reason: str | None = None
    details: dict[str, str] | None = None

    @classmethod
    def reject(cls, code: str, reason: str, **details: object) -> PositionSize:
        return cls(
            approved=False,
            reason_code=code,
            reason=reason,
            details={key: str(value) for key, value in details.items()} or None,
        )


def _round_down_to_step(value: Decimal, step: Decimal | None) -> Decimal:
    """Round a quantity down onto the exchange's lot grid.

    Down, never nearest: rounding up could push notional past a cap that was
    just checked, or past the balance actually available.
    """
    if step is None or step <= 0:
        return value
    steps = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return steps * step


def calculate_position_size(
    *,
    equity: Decimal,
    available_quote: Decimal,
    entry_price: Decimal,
    stop_price: Decimal | None,
    risk: RiskConfig,
    filters: SymbolFilters,
    taker_fee: Decimal,
    current_asset_exposure: Decimal = Decimal(0),
    current_portfolio_exposure: Decimal = Decimal(0),
) -> PositionSize:
    """Size a long Spot entry, or explain why it cannot be taken.

    Exposure arguments are the *existing* exposure in quote currency, so the
    caps in §31 are applied to the position this order would create on top of
    what is already open -- not to the order in isolation.
    """
    if equity <= 0:
        return PositionSize.reject(
            REJECT_NO_EQUITY, "Account equity is zero or negative; no position can be sized."
        )
    if entry_price <= 0:
        return PositionSize.reject(
            REJECT_NO_STOP_DISTANCE, f"Entry price must be positive, got {entry_price}."
        )
    if stop_price is None or stop_price >= entry_price:
        # A long entry needs a stop strictly below entry; without one the
        # risk-per-trade cap has no meaning and sizing would be arbitrary.
        return PositionSize.reject(
            REJECT_NO_STOP_DISTANCE,
            "A long entry requires a stop strictly below the entry price.",
            entry_price=entry_price,
            stop_price=stop_price,
        )

    stop_distance = entry_price - stop_price
    risk_amount = equity * risk.max_risk_per_trade
    quantity = risk_amount / stop_distance

    # --- Apply the §31 exposure caps, tightest wins ---------------------
    caps: list[tuple[str, Decimal]] = [
        ("max_position_size", equity * risk.max_position_size),
        ("max_asset_exposure", equity * risk.max_asset_exposure - current_asset_exposure),
        (
            "max_portfolio_exposure",
            equity * risk.max_portfolio_exposure - current_portfolio_exposure,
        ),
        ("available_quote", available_quote),
    ]
    binding_cap, cap_notional = min(caps, key=lambda item: item[1])
    if cap_notional <= 0:
        return PositionSize.reject(
            REJECT_TRADE_NOT_ECONOMIC,
            f"No headroom left under {binding_cap}; existing exposure already fills it.",
            binding_cap=binding_cap,
            headroom=cap_notional,
        )

    if quantity * entry_price > cap_notional:
        quantity = cap_notional / entry_price

    # --- Exchange filters (§33): the exchange's rules, not assumed ones ---
    if filters.max_qty is not None and quantity > filters.max_qty:
        quantity = filters.max_qty

    quantity = _round_down_to_step(quantity, filters.step_size)

    if quantity <= 0:
        return PositionSize.reject(
            REJECT_TRADE_NOT_ECONOMIC,
            "Position rounds down to zero at this symbol's step size.",
            step_size=filters.step_size,
        )
    if filters.min_qty is not None and quantity < filters.min_qty:
        return PositionSize.reject(
            REJECT_BELOW_MIN_QTY,
            f"Sized quantity {quantity} is below the exchange minimum {filters.min_qty}.",
            quantity=quantity,
            min_qty=filters.min_qty,
        )

    notional = quantity * entry_price
    if (
        filters.min_notional is not None
        and filters.apply_min_to_market
        and notional < filters.min_notional
    ):
        return PositionSize.reject(
            REJECT_BELOW_MIN_NOTIONAL,
            (
                f"Order value {notional:.4f} is below the exchange minimum "
                f"{filters.min_notional}. This is expected on a small account (§88)."
            ),
            notional=notional,
            min_notional=filters.min_notional,
        )

    estimated_fee = notional * taker_fee
    if notional + estimated_fee > available_quote:
        return PositionSize.reject(
            REJECT_INSUFFICIENT_BALANCE,
            f"Order plus fees ({notional + estimated_fee:.4f}) exceeds available balance.",
            required=notional + estimated_fee,
            available=available_quote,
        )

    # Fees are a real cost of the round trip: an order whose expected edge is
    # smaller than the fees it pays is not economic regardless of sizing (§86).
    round_trip_fee = estimated_fee * 2
    if round_trip_fee >= risk_amount:
        return PositionSize.reject(
            REJECT_TRADE_NOT_ECONOMIC,
            (
                f"Round-trip fees ({round_trip_fee:.4f}) meet or exceed the amount "
                f"risked ({risk_amount:.4f}); the trade cannot pay for itself."
            ),
            round_trip_fee=round_trip_fee,
            risk_amount=risk_amount,
        )

    return PositionSize(
        approved=True,
        quantity=quantity,
        notional=notional,
        risk_amount=quantity * stop_distance,
        estimated_fee=estimated_fee,
        details={"binding_cap": binding_cap},
    )
