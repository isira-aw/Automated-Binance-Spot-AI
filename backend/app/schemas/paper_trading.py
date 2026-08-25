"""Schemas for the paper trading execution namespaces (§11B, §31, §41, §59)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OpenOrderRequest(BaseModel):
    symbol: str
    stop_price: float
    take_profit: float | None = None
    trailing_distance: float | None = None
    signal_id: int | None = None


class PaperOrderOut(BaseModel):
    id: int
    client_order_id: str
    signal_id: int | None
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: float
    price: float | None
    filled_quantity: float
    average_fill_price: float | None
    fee: float
    submitted_at: datetime
    strategy_version: str | None


class PaperPositionOut(BaseModel):
    id: int
    symbol: str
    status: str
    quantity: float
    entry_price: float
    entry_time: datetime
    exit_price: float | None
    exit_time: datetime | None
    stop_loss: float | None
    take_profit: float | None
    trailing_stop: float | None
    unrealised_pnl: float | None
    realised_pnl: float | None
    fees_paid: float
    signal_id: int | None
    strategy_version: str | None


class TradeOut(BaseModel):
    id: int
    venue: str
    symbol: str
    position_id: int | None
    signal_id: int | None
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    gross_pnl: float
    fees: float
    slippage_cost: float
    net_pnl: float
    return_pct: float
    mae: float | None
    mfe: float | None
    exit_reason: str | None
    strategy_version: str | None
    model_version: str | None
