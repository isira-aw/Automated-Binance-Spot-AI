"""In-memory portfolio accounting for paper trading and backtesting (§11B, §41).

Shared by both engines so a backtest's equity curve is produced by the same
arithmetic that produces paper trading's -- §35 requires the backtester to
reuse these components rather than reimplement them.

All money is :class:`~decimal.Decimal`. Float accumulation over thousands of
fills drifts, and an equity curve that drifts is a performance metric that
lies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models.enums import PositionStatus


@dataclass
class OpenPosition:
    """A long Spot position. No shorts, no leverage (§1)."""

    symbol: str
    quantity: Decimal
    entry_price: Decimal
    entry_time: datetime
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    trailing_distance: Decimal | None = None
    fees_paid: Decimal = Decimal(0)
    highest_price: Decimal | None = None
    lowest_price: Decimal | None = None
    signal_id: int | None = None
    status: PositionStatus = PositionStatus.OPEN

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.entry_price

    def market_value(self, price: Decimal) -> Decimal:
        return self.quantity * price

    def unrealised_pnl(self, price: Decimal) -> Decimal:
        """Excludes the exit fee not yet paid -- that is booked on close."""
        return (price - self.entry_price) * self.quantity - self.fees_paid

    def observe(self, high: Decimal, low: Decimal) -> None:
        """Track excursion extremes for MAE/MFE (§22, §41)."""
        self.highest_price = high if self.highest_price is None else max(self.highest_price, high)
        self.lowest_price = low if self.lowest_price is None else min(self.lowest_price, low)

    def mae(self) -> Decimal | None:
        """Maximum adverse excursion as a fraction of entry price."""
        if self.lowest_price is None or self.entry_price <= 0:
            return None
        return (self.lowest_price - self.entry_price) / self.entry_price

    def mfe(self) -> Decimal | None:
        """Maximum favourable excursion as a fraction of entry price."""
        if self.highest_price is None or self.entry_price <= 0:
            return None
        return (self.highest_price - self.entry_price) / self.entry_price


@dataclass
class ClosedTrade:
    """A completed round trip, net of every cost (§41)."""

    symbol: str
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_time: datetime
    exit_time: datetime
    gross_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    net_pnl: Decimal
    return_pct: Decimal
    exit_reason: str
    mae: Decimal | None = None
    mfe: Decimal | None = None
    signal_id: int | None = None

    @property
    def is_win(self) -> bool:
        """Net of fees -- a trade that only wins gross is not a winning trade."""
        return self.net_pnl > 0


@dataclass
class Portfolio:
    """Cash, open positions, and the realised record (§42)."""

    quote_balance: Decimal
    initial_balance: Decimal
    positions: dict[str, OpenPosition] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    realised_pnl: Decimal = Decimal(0)
    total_fees: Decimal = Decimal(0)
    peak_equity: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if self.peak_equity <= 0:
            self.peak_equity = self.initial_balance

    # -- valuation ------------------------------------------------------

    def positions_value(self, prices: dict[str, Decimal]) -> Decimal:
        """Mark open positions to market.

        A symbol missing from ``prices`` is valued at its entry price rather
        than dropped: silently valuing a held position at zero would show a
        phantom loss and could trip the drawdown halt on a data gap alone.
        """
        total = Decimal(0)
        for symbol, position in self.positions.items():
            price = prices.get(symbol, position.entry_price)
            total += position.market_value(price)
        return total

    def equity(self, prices: dict[str, Decimal]) -> Decimal:
        return self.quote_balance + self.positions_value(prices)

    def unrealised_pnl(self, prices: dict[str, Decimal]) -> Decimal:
        return sum(
            (
                position.unrealised_pnl(prices.get(symbol, position.entry_price))
                for symbol, position in self.positions.items()
            ),
            Decimal(0),
        )

    def update_peak_equity(self, prices: dict[str, Decimal]) -> None:
        self.peak_equity = max(self.peak_equity, self.equity(prices))

    def drawdown_fraction(self, prices: dict[str, Decimal]) -> Decimal:
        if self.peak_equity <= 0:
            return Decimal(0)
        drop = self.peak_equity - self.equity(prices)
        return max(Decimal(0), drop / self.peak_equity)

    # -- mutations ------------------------------------------------------

    def open_position(
        self,
        *,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal,
        timestamp: datetime,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        trailing_distance: Decimal | None = None,
        signal_id: int | None = None,
    ) -> OpenPosition:
        cost = quantity * price + fee
        if cost > self.quote_balance:
            raise ValueError(
                f"Cannot open {symbol}: cost {cost} exceeds balance {self.quote_balance}."
            )
        if symbol in self.positions:
            raise ValueError(f"A position in {symbol} is already open.")

        self.quote_balance -= cost
        self.total_fees += fee
        position = OpenPosition(
            symbol=symbol,
            quantity=quantity,
            entry_price=price,
            entry_time=timestamp,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_distance=trailing_distance,
            fees_paid=fee,
            highest_price=price,
            lowest_price=price,
            signal_id=signal_id,
        )
        self.positions[symbol] = position
        return position

    def close_position(
        self,
        *,
        symbol: str,
        price: Decimal,
        fee: Decimal,
        slippage_cost: Decimal,
        timestamp: datetime,
        reason: str,
    ) -> ClosedTrade:
        position = self.positions.pop(symbol, None)
        if position is None:
            raise ValueError(f"No open position in {symbol} to close.")

        proceeds = position.quantity * price
        self.quote_balance += proceeds - fee
        self.total_fees += fee

        gross_pnl = (price - position.entry_price) * position.quantity
        total_fees = position.fees_paid + fee
        net_pnl = gross_pnl - total_fees
        self.realised_pnl += net_pnl

        cost_basis = position.cost_basis
        return_pct = net_pnl / cost_basis if cost_basis > 0 else Decimal(0)

        trade = ClosedTrade(
            symbol=symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            exit_price=price,
            entry_time=position.entry_time,
            exit_time=timestamp,
            gross_pnl=gross_pnl,
            fees=total_fees,
            slippage_cost=slippage_cost,
            net_pnl=net_pnl,
            return_pct=return_pct,
            exit_reason=reason,
            mae=position.mae(),
            mfe=position.mfe(),
            signal_id=position.signal_id,
        )
        self.closed_trades.append(trade)
        return trade

    # -- risk-engine inputs ---------------------------------------------

    @property
    def consecutive_losses(self) -> int:
        """Losing trades since the last win, for the §31 loss-streak halt."""
        streak = 0
        for trade in reversed(self.closed_trades):
            if trade.is_win:
                break
            streak += 1
        return streak

    def asset_exposure(self, prices: dict[str, Decimal]) -> dict[str, Decimal]:
        return {
            symbol: position.market_value(prices.get(symbol, position.entry_price))
            for symbol, position in self.positions.items()
        }
