"""Signals, orders, positions, trades, portfolio and risk tables.

Paper and live order/position tables are kept separate so that paper activity
can never be mistaken for real activity (§42), while `trades` holds the closed
round-trips from every venue with an explicit ``venue`` column.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class Signal(Base, TimestampMixin):
    """A fused trading signal (§30).

    Persisted whether or not it results in a trade, together with the full
    decision chain, so every decision is reproducible (§79, §80).
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Unified [0,1] scale (§30a): 0.5 is neutral.
    score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fusion_method: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_price: Mapped[float | None] = mapped_column(Numeric(24, 10))
    risk_decision: Mapped[str | None] = mapped_column(String(16), index=True)
    risk_reason: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str] = mapped_column(String(24), nullable=False, default="PAPER")

    components: Mapped[list["SignalComponent"]] = relationship(
        back_populates="signal", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "open_time", "strategy_version", "venue",
            name="uq_signals_symbol",
        ),
    )


class SignalComponent(Base):
    """One component's contribution to a fused signal (§30b, §81)."""

    __tablename__ = "signal_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    version: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    signal: Mapped[Signal] = relationship(back_populates="components")

    __table_args__ = (
        UniqueConstraint("signal_id", "kind", name="uq_signal_components_signal_id"),
    )


class _OrderColumns:
    """Columns shared by paper and live order tables."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(28, 12), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(24, 10))
    filled_quantity: Mapped[float] = mapped_column(Numeric(28, 12), nullable=False, default=0)
    average_fill_price: Mapped[float | None] = mapped_column(Numeric(24, 10))
    fee: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    fee_asset: Mapped[str | None] = mapped_column(String(16))
    slippage: Mapped[float | None] = mapped_column(Numeric(18, 10))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_exchange: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    strategy_version: Mapped[str | None] = mapped_column(String(32))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class PaperOrder(Base, TimestampMixin, _OrderColumns):
    __tablename__ = "paper_orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_paper_orders_client_order_id"),
    )


class LiveOrder(Base, TimestampMixin, _OrderColumns):
    __tablename__ = "live_orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_live_orders_client_order_id"),
    )


class _PositionColumns:
    """Columns shared by paper and live position tables (Spot long-only)."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(28, 12), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric(24, 10))
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_loss: Mapped[float | None] = mapped_column(Numeric(24, 10))
    take_profit: Mapped[float | None] = mapped_column(Numeric(24, 10))
    trailing_stop: Mapped[float | None] = mapped_column(Numeric(24, 10))
    unrealised_pnl: Mapped[float | None] = mapped_column(Numeric(24, 10))
    realised_pnl: Mapped[float | None] = mapped_column(Numeric(24, 10))
    fees_paid: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(32))


class PaperPosition(Base, TimestampMixin, _PositionColumns):
    __tablename__ = "paper_positions"


class LivePosition(Base, TimestampMixin, _PositionColumns):
    __tablename__ = "live_positions"


class Trade(Base, TimestampMixin):
    """A closed round-trip, from any venue (§41 metric inputs)."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    venue: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, index=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="BUY")
    quantity: Mapped[float] = mapped_column(Numeric(28, 12), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    exit_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    gross_pnl: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    fees: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    slippage_cost: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    net_pnl: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    return_pct: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    mae: Mapped[float | None] = mapped_column(Numeric(18, 8))
    mfe: Mapped[float | None] = mapped_column(Numeric(18, 8))
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    strategy_version: Mapped[str | None] = mapped_column(String(32), index=True)
    model_version: Mapped[str | None] = mapped_column(String(64), index=True)

    __table_args__ = (Index("ix_trades_venue_exit_time", "venue", "exit_time"),)


class PortfolioSnapshot(Base):
    """Equity curve point per venue (§41 drawdown/Sharpe inputs)."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    venue: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    quote_balance: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    positions_value: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    equity: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    realised_pnl: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    unrealised_pnl: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("venue", "timestamp", name="uq_portfolio_snapshots_venue"),
    )


class RiskEvent(Base):
    """Every risk-engine decision that blocked, paused, or flagged (§31, §45)."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    venue: Mapped[str] = mapped_column(String(24), nullable=False, default="PAPER")
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rule: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ExecutionEvent(Base):
    """Trade-lifecycle state transitions (§34)."""

    __tablename__ = "execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    venue: Mapped[str] = mapped_column(String(24), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(32))
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, index=True)
    position_id: Mapped[int | None] = mapped_column(Integer, index=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
