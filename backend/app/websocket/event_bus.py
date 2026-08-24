"""In-process publish/subscribe bus for outbound WebSocket events.

Publishers (market data, trading engine, risk engine, workers) never hold a
reference to a socket; they publish an :class:`Event` and the connection
manager fans it out.  Every subscriber queue is bounded — a slow client drops
its own oldest events rather than growing memory without limit (§53).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.events import Event, EventType
from app.core.logging_config import get_logger

logger = get_logger("websocket.event_bus")


class Subscriber:
    """A bounded queue fed by the bus."""

    def __init__(self, maxsize: int, topics: set[EventType] | None = None) -> None:
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.topics: set[EventType] | None = topics
        self.dropped = 0

    def wants(self, event: Event) -> bool:
        return self.topics is None or event.event in self.topics

    def offer(self, event: Event) -> None:
        """Non-blocking put; drops the oldest event when the queue is full."""
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the oldest event so a stalled client bounds its own memory.
            with contextlib.suppress(asyncio.QueueEmpty):  # racing consumer
                self.queue.get_nowait()
            self.dropped += 1
            with contextlib.suppress(asyncio.QueueFull):  # racing consumer
                self.queue.put_nowait(event)


class EventBus:
    def __init__(self, queue_size: int = 500) -> None:
        self._queue_size = queue_size
        self._subscribers: set[Subscriber] = set()
        self._lock = asyncio.Lock()

    @property
    def queue_size(self) -> int:
        return self._queue_size

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, event: Event) -> None:
        async with self._lock:
            targets = [s for s in self._subscribers if s.wants(event)]
        for subscriber in targets:
            subscriber.offer(event)

    async def add(self, subscriber: Subscriber) -> None:
        async with self._lock:
            self._subscribers.add(subscriber)

    async def remove(self, subscriber: Subscriber) -> None:
        async with self._lock:
            self._subscribers.discard(subscriber)

    @asynccontextmanager
    async def subscribe(
        self, topics: set[EventType] | None = None
    ) -> AsyncIterator[Subscriber]:
        subscriber = Subscriber(self._queue_size, topics)
        await self.add(subscriber)
        try:
            yield subscriber
        finally:
            await self.remove(subscriber)
            if subscriber.dropped:
                logger.warning(
                    "Subscriber dropped events due to backpressure",
                    extra={"event_type": "ws_backpressure", "dropped": subscriber.dropped},
                )


_bus: EventBus | None = None


def init_event_bus(queue_size: int) -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus(queue_size)
    return _bus


def get_event_bus() -> EventBus:
    if _bus is None:
        raise RuntimeError("Event bus is not initialised; call init_event_bus().")
    return _bus


def reset_event_bus() -> None:
    """Test helper — drops the process-wide bus."""
    global _bus
    _bus = None
