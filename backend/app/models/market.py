"""Market data, technical features, regimes, and pattern tables."""

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


class MarketDataMetadata(Base, TimestampMixin):
    """Per-symbol/timeframe coverage and integrity state (§17)."""

    __tablename__ = "market_data_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="BINANCE")
    first_candle_open: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_candle_open: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_candles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_integrity_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    integrity_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "source", name="uq_market_data_metadata_symbol"),
    )


class Candle(Base):
    """OHLCV candle.  ``open_time`` is the UTC candle boundary (§16).

    Only rows with ``is_closed = true`` may be used as feature inputs.
    """

    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(24, 10), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(28, 10), nullable=False)
    quote_volume: Mapped[float | None] = mapped_column(Numeric(28, 10))
    trades: Mapped[int | None] = mapped_column(Integer)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="BINANCE")

    __table_args__ = (
        # The natural key.  Also the primary read path, so no extra index on
        # symbol/timeframe is needed (§102: avoid redundant indexes on the
        # largest table).
        UniqueConstraint("symbol", "timeframe", "open_time", name="uq_candles_symbol"),
    )


class TechnicalFeature(Base):
    """Computed indicator vector for one closed candle (§19).

    ``feature_version`` pins the generation logic so a model can refuse to run
    against incompatible features (§78).
    """

    __tablename__ = "technical_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "open_time", "feature_version",
            name="uq_technical_features_symbol",
        ),
    )


class MarketRegime(Base):
    """Detected regime per symbol/timeframe (§23) — Tier 2."""

    __tablename__ = "market_regimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    regime: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "open_time", "detector_version", name="uq_market_regimes_symbol"),
    )


class Pattern(Base):
    """A detected chart/candlestick pattern occurrence (§21) — Tier 2."""

    __tablename__ = "patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Filled in by the outcome evaluator, net of fees and slippage (§22).
    outcome_return: Mapped[float | None] = mapped_column(Numeric(18, 8))
    outcome_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_patterns_symbol_type_end", "symbol", "pattern_type", "end_time"),
    )


class PatternStatistic(Base, TimestampMixin):
    """Out-of-sample validation verdict per pattern type (§22).

    A pattern with no demonstrated out-of-sample edge is KEPT as a REJECTED row
    — that is a healthy result, not a bug.
    """

    __tablename__ = "pattern_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    in_sample_range: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    out_of_sample_range: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    win_rate: Mapped[float | None] = mapped_column(Numeric(8, 5))
    expected_return: Mapped[float | None] = mapped_column(Numeric(18, 8))
    profit_factor: Mapped[float | None] = mapped_column(Numeric(12, 5))
    sharpe: Mapped[float | None] = mapped_column(Numeric(12, 5))
    max_drawdown: Mapped[float | None] = mapped_column(Numeric(12, 5))
    mae: Mapped[float | None] = mapped_column(Numeric(18, 8))
    mfe: Mapped[float | None] = mapped_column(Numeric(18, 8))
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)  # KEEP | REJECT
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "pattern_type", "symbol", "timeframe", "detector_version",
            name="uq_pattern_statistics_pattern_type",
        ),
    )
