"""Schemas for the backtests namespace (§35, §41, §82, §59)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class BacktestRunRequest(BaseModel):
    symbol: str
    timeframe: str
    range_start: datetime
    range_end: datetime


class BacktestTradeOut(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    return_pct: float
    mae: float | None
    mfe: float | None
    exit_reason: str | None


class BacktestRunOut(BaseModel):
    id: int
    job_id: str
    status: str
    symbols: list[str]
    timeframe: str
    range_start: datetime
    range_end: datetime
    initial_capital: float
    maker_fee: float
    taker_fee: float
    slippage_bps: float
    strategy_version: str
    feature_version: str | None
    config: dict[str, Any] | None
    metrics: dict[str, Any] | None
    assumptions: dict[str, Any] | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    created_at: datetime
    trades: list[BacktestTradeOut]


class BacktestRunSummaryOut(BaseModel):
    """The list view: everything but the (potentially large) trade log."""

    id: int
    job_id: str
    status: str
    symbols: list[str]
    timeframe: str
    range_start: datetime
    range_end: datetime
    strategy_version: str
    metrics: dict[str, Any] | None
    created_at: datetime
