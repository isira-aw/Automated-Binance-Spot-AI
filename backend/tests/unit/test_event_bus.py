"""Event bus fan-out, filtering and backpressure (§13, §53)."""

from __future__ import annotations

import pytest

from app.core.events import Event, EventType
from app.websocket.event_bus import EventBus, Subscriber


@pytest.fixture
def bus() -> EventBus:
    return EventBus(queue_size=3)


async def test_event_reaches_every_subscriber(bus: EventBus):
    async with bus.subscribe() as a, bus.subscribe() as b:
        await bus.publish(Event.of(EventType.TICKER_UPDATE, symbol="BTCUSDT"))
        assert (await a.queue.get()).data["symbol"] == "BTCUSDT"
        assert (await b.queue.get()).data["symbol"] == "BTCUSDT"


async def test_topic_filter_excludes_unsubscribed_events(bus: EventBus):
    async with bus.subscribe({EventType.RISK_EVENT}) as sub:
        await bus.publish(Event.of(EventType.TICKER_UPDATE))
        assert sub.queue.empty()
        await bus.publish(Event.of(EventType.RISK_EVENT, rule="max_daily_loss"))
        assert (await sub.queue.get()).event is EventType.RISK_EVENT


async def test_slow_subscriber_drops_oldest_instead_of_growing(bus: EventBus):
    """Backpressure is bounded: a stalled client can never exhaust memory."""
    async with bus.subscribe() as sub:
        for index in range(10):
            await bus.publish(Event.of(EventType.TICKER_UPDATE, index=index))
        assert sub.queue.qsize() == 3
        assert sub.dropped == 7
        # The three most recent events survive.
        received = [(await sub.queue.get()).data["index"] for _ in range(3)]
        assert received == [7, 8, 9]


async def test_subscriber_is_removed_on_context_exit(bus: EventBus):
    async with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_publish_with_no_subscribers_is_a_no_op(bus: EventBus):
    await bus.publish(Event.of(EventType.SYSTEM_STATUS))
    assert bus.subscriber_count == 0


def test_event_envelope_matches_the_documented_contract():
    event = Event.of(EventType.SIGNAL_CREATED, symbol="ETHUSDT")
    payload = event.model_dump()
    assert set(payload) == {"event", "timestamp", "data"}
    assert payload["event"] == "signal_created"
    assert payload["timestamp"].endswith("+00:00")


def test_subscriber_offer_is_non_blocking():
    subscriber = Subscriber(maxsize=1)
    subscriber.offer(Event.of(EventType.HEARTBEAT))
    subscriber.offer(Event.of(EventType.HEARTBEAT))
    assert subscriber.queue.qsize() == 1
