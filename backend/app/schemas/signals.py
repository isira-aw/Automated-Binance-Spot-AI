"""Schemas for the signals namespace (§30, §59)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SignalComponentOut(BaseModel):
    kind: str
    score: float
    weight: float
    confidence: float | None
    version: str | None
    active: bool
    details: dict[str, Any] | None


class SignalOut(BaseModel):
    id: int
    symbol: str
    timeframe: str
    open_time: datetime
    generated_at: datetime
    action: str
    score: float
    confidence: float
    reason_codes: list[str]
    strategy_version: str
    fusion_method: str
    reference_price: float | None
    risk_decision: str | None
    risk_reason: str | None
    venue: str
    components: list[SignalComponentOut]


class GenerateSignalRequest(BaseModel):
    symbol: str
    timeframe: str
