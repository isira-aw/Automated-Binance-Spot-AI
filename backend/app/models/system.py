"""System, settings, and audit tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class SystemSetting(Base, TimestampMixin):
    """Key/value application configuration persisted across restarts (§89)."""

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ExchangeSetting(Base, TimestampMixin):
    """Per-exchange metadata and connection configuration (never secrets)."""

    __tablename__ = "exchange_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="BINANCE")
    testnet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    maker_fee: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0.001)
    taker_fee: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0.001)
    rate_limits: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    server_time_offset_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("exchange", "testnet", name="uq_exchange_settings_exchange"),)


class Asset(Base, TimestampMixin):
    """Tradable Spot symbol plus its live exchange filters (§33)."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    base_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str | None] = mapped_column(String(32))
    # Snapshot of Binance symbol filters (min notional, lot size, tick size...).
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    filters_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemEvent(Base):
    """Operational events surfaced to the System page and log viewer (§48)."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    __table_args__ = (Index("ix_system_events_component_ts", "component", "timestamp"),)


class AuditLog(Base):
    """Full decision audit trail (§47).

    One row per trading decision, holding every input that produced it so the
    decision can be reconstructed later.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(8))
    signal_id: Mapped[int | None] = mapped_column(Integer, index=True)
    trade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(32), index=True)
    model_version: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
