"""Schemas for the market data namespace (§17, §59)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CoverageOut(BaseModel):
    """One row of ``GET /market/coverage`` — per symbol/timeframe status."""

    symbol: str
    timeframe: str
    source: str
    first_candle_open: datetime | None
    last_candle_open: datetime | None
    candle_count: int
    missing_candles: int
    last_integrity_check: datetime | None
    is_clean: bool | None = None


class CandleOut(BaseModel):
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float | None = None
    trades: int | None = None
    is_closed: bool


class IngestionResultOut(BaseModel):
    symbol: str
    timeframe: str
    pages_fetched: int
    candles_inserted: int
    candles_updated: int
    reached_present: bool
    stopped_reason: str
    error: str | None = None


class BackfillJobOut(BaseModel):
    started_at: str
    finished_at: str | None
    running: bool
    error: str | None = None
    total_candles_inserted: int
    results: list[IngestionResultOut]


class IntegrityReportOut(BaseModel):
    symbol: str
    timeframe: str
    candle_count: int
    expected_count: int | None
    missing_candles: int
    duplicate_open_times: int
    misaligned_timestamps: list[str]
    ohlc_violations: list[str]
    non_positive_values: list[str]
    abnormal_moves: list[str]
    is_clean: bool
    checked_at: str


class FeatureVectorOut(BaseModel):
    symbol: str
    timeframe: str
    open_time: datetime
    feature_version: str
    features: dict[str, float | None]
