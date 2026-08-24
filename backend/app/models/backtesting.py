"""Backtest run and backtest trade tables (§35, §82)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin


class BacktestRun(Base, TimestampMixin):
    """One backtest, with the assumptions it ran under recorded explicitly.

    ``assumptions`` carries the look-ahead audit disclosures required by §82 —
    fee model, slippage model, fill model, and the leakage checks performed.
    A run without those disclosures is not a meaningful result.
    """

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    maker_fee: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    taker_fee: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    slippage_bps: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_version: Mapped[str | None] = mapped_column(String(64), index=True)
    feature_version: Mapped[str | None] = mapped_column(String(32))
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    assumptions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    trades: Mapped[list["BacktestTrade"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="BUY")
    quantity: Mapped[float] = mapped_column(Numeric(28, 12), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_price: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    gross_pnl: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    fees: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    slippage_cost: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False, default=0)
    net_pnl: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    return_pct: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    mae: Mapped[float | None] = mapped_column(Numeric(18, 8))
    mfe: Mapped[float | None] = mapped_column(Numeric(18, 8))
    exit_reason: Mapped[str | None] = mapped_column(String(32))
    signal_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    run: Mapped[BacktestRun] = relationship(back_populates="trades")

    __table_args__ = (Index("ix_backtest_trades_run_symbol", "run_id", "symbol"),)
