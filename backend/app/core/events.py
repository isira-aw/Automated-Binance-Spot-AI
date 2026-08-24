"""WebSocket event contract (§13).

The event *names* are part of the frontend/backend contract and are mirrored in
``frontend/src/types/events.ts``.  Events that belong to unbuilt phases are
declared here but are never emitted with fabricated data (§96).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.core.time_utils import utc_now


class EventType(str, Enum):
    # --- Market data ---
    MARKET_UPDATE = "market_update"
    TICKER_UPDATE = "ticker_update"
    CANDLE_CLOSED = "candle_closed"
    # --- Signals ---
    SIGNAL_CREATED = "signal_created"
    SIGNAL_UPDATED = "signal_updated"
    # --- Orders / positions ---
    ORDER_CREATED = "order_created"
    ORDER_UPDATED = "order_updated"
    ORDER_FILLED = "order_filled"
    POSITION_UPDATED = "position_updated"
    PORTFOLIO_UPDATED = "portfolio_updated"
    # --- Risk ---
    RISK_EVENT = "risk_event"
    # --- Models (Tier 1 LightGBM; Tier 2 extends) ---
    MODEL_STATUS = "model_status"
    TRAINING_STATUS = "training_status"
    BACKTEST_STATUS = "backtest_status"
    # --- Tier 2 ---
    NEWS_UPDATE = "news_update"
    # --- System ---
    SYSTEM_STATUS = "system_status"
    LOG_EVENT = "log_event"
    # --- Transport-level (not business events) ---
    HEARTBEAT = "heartbeat"
    SUBSCRIPTION_UPDATED = "subscription_updated"
    ERROR = "error"


class Event(BaseModel):
    """The single envelope every WebSocket message uses."""

    event: EventType
    timestamp: str = Field(default_factory=lambda: utc_now().isoformat())
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def of(cls, event: EventType, **data: Any) -> Event:
        return cls(event=event, data=data)
