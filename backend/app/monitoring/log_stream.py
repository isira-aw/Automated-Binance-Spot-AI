"""Bridge structured log records onto the WebSocket bus (§48).

Only WARNING+ records and explicitly tagged trading/risk/model records are
streamed, so the live log viewer stays useful rather than drowning in DEBUG.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.events import Event, EventType
from app.websocket.event_bus import EventBus

STREAMED_EVENT_PREFIXES = ("trade_", "risk_", "model_", "signal_", "order_", "position_")


class WebSocketLogHandler(logging.Handler):
    """Publishes log records as ``log_event`` messages.

    The handler is attached from the running event loop and schedules publishes
    onto it, so logging from worker threads never blocks.
    """

    def __init__(
        self,
        bus: EventBus,
        loop: asyncio.AbstractEventLoop,
        level: int = logging.WARNING,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self._bus = bus
        self._loop = loop
        self._min_level = level

    def _should_stream(self, record: logging.LogRecord) -> bool:
        if record.levelno >= self._min_level:
            return True
        event_type = str(getattr(record, "event_type", ""))
        return event_type.startswith(STREAMED_EVENT_PREFIXES)

    def emit(self, record: logging.LogRecord) -> None:
        if not self._should_stream(record):
            return
        try:
            event = Event.of(
                EventType.LOG_EVENT,
                level=record.levelname,
                component=getattr(record, "component", record.name),
                event_type=getattr(record, "event_type", "log"),
                message=record.getMessage(),
            )
            asyncio.run_coroutine_threadsafe(self._bus.publish(event), self._loop)
        except Exception:
            self.handleError(record)
