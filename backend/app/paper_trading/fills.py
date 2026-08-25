"""Fill simulation: slippage, fees, partial fills (§11B, §83, §87).

Pure functions with no I/O and no clock of their own, so the backtesting
engine (§35) reuses this exact code rather than growing a parallel fill model
that could drift from what paper trading does. A backtest whose fills differ
from paper trading's is not a backtest of this system.

Fees and slippage are always applied. There is no zero-cost path through this
module -- §87 and §82 both call out a zero-fee/zero-slippage simulation as a
way to produce results that cannot happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from app.models.enums import OrderSide

BPS = Decimal("10000")


@dataclass(frozen=True)
class FillResult:
    """The outcome of attempting to fill an order against a market."""

    filled_quantity: Decimal
    average_price: Decimal
    fee: Decimal
    slippage_cost: Decimal
    is_partial: bool

    @property
    def gross_value(self) -> Decimal:
        return self.filled_quantity * self.average_price

    @property
    def is_empty(self) -> bool:
        return self.filled_quantity <= 0


def apply_slippage(
    reference_price: Decimal, side: OrderSide, slippage_bps: Decimal
) -> Decimal:
    """Move the fill price against the trader, always.

    Slippage that sometimes helps is a modelling error in a backtest: it
    turns an execution cost into a coin flip and flatters results over many
    trades. A buy fills higher, a sell fills lower, every time.
    """
    adjustment = reference_price * slippage_bps / BPS
    if side is OrderSide.BUY:
        return reference_price + adjustment
    return reference_price - adjustment


def simulate_fill(
    *,
    requested_quantity: Decimal,
    reference_price: Decimal,
    side: OrderSide,
    fee_rate: Decimal,
    slippage_bps: Decimal,
    available_liquidity: Decimal | None = None,
    step_size: Decimal | None = None,
) -> FillResult:
    """Fill an order at ``reference_price`` adjusted for slippage and fees.

    ``available_liquidity`` caps the fill to model a partial fill; ``None``
    means the full quantity fills, which is the right default for the liquid
    majors this system trades but explicitly *not* an assumption the
    backtester should make for thin books (§82's "impossible liquidity" audit).
    """
    if requested_quantity <= 0 or reference_price <= 0:
        return FillResult(Decimal(0), Decimal(0), Decimal(0), Decimal(0), is_partial=False)

    fill_quantity = requested_quantity
    if available_liquidity is not None and available_liquidity < fill_quantity:
        fill_quantity = available_liquidity

    if step_size is not None and step_size > 0:
        steps = (fill_quantity / step_size).to_integral_value(rounding=ROUND_DOWN)
        fill_quantity = steps * step_size

    if fill_quantity <= 0:
        return FillResult(Decimal(0), Decimal(0), Decimal(0), Decimal(0), is_partial=False)

    fill_price = apply_slippage(reference_price, side, slippage_bps)
    gross = fill_quantity * fill_price
    fee = gross * fee_rate
    # Slippage cost is reported against the price the decision was made at,
    # so post-trade analysis can separate "the market moved" from "we paid
    # the spread" (§41 tracks slippage as its own metric).
    slippage_cost = abs(fill_price - reference_price) * fill_quantity

    return FillResult(
        filled_quantity=fill_quantity,
        average_price=fill_price,
        fee=fee,
        slippage_cost=slippage_cost,
        is_partial=fill_quantity < requested_quantity,
    )


def exit_reason_for_bar(
    *,
    high: Decimal,
    low: Decimal,
    stop_loss: Decimal | None,
    take_profit: Decimal | None,
) -> str | None:
    """Which exit (if any) a long position hits during one candle.

    When a single bar's range spans both the stop and the target, the stop is
    reported. Intrabar order is unknowable from OHLC alone, and assuming the
    favourable one is exactly how a backtest manufactures profits that never
    existed (§82). The pessimistic assumption is the only honest one here.
    """
    hit_stop = stop_loss is not None and low <= stop_loss
    hit_target = take_profit is not None and high >= take_profit

    if hit_stop:
        return "STOP_LOSS"
    if hit_target:
        return "TAKE_PROFIT"
    return None


def update_trailing_stop(
    *,
    current_stop: Decimal | None,
    high: Decimal,
    trailing_distance: Decimal | None,
) -> Decimal | None:
    """Raise a long position's trailing stop; never lower it.

    A trailing stop that can move down is not a trailing stop -- it would let
    a position give back more than the trail was set to permit.
    """
    if trailing_distance is None or trailing_distance <= 0:
        return current_stop
    candidate = high - trailing_distance
    if current_stop is None:
        return candidate
    return max(current_stop, candidate)
