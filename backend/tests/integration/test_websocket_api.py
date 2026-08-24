"""WebSocket contract: envelope, heartbeat, subscriptions, fan-out (§13)."""

from __future__ import annotations

import json

from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.events import Event, EventType


def read_until(ws, event: EventType, limit: int = 20) -> dict:
    """Read frames until ``event`` arrives (skipping heartbeats)."""
    for _ in range(limit):
        message = json.loads(ws.receive_text())
        if message["event"] == event.value:
            return message
    raise AssertionError(f"Did not receive {event.value} within {limit} frames")


def test_connection_greeting_uses_the_event_envelope(client: TestClient):
    with client.websocket_connect("/api/v1/ws") as ws:
        greeting = json.loads(ws.receive_text())
        assert set(greeting) == {"event", "timestamp", "data"}
        assert greeting["event"] == "system_status"
        assert greeting["data"]["status"] == "connected"
        assert greeting["data"]["client_id"]


def test_server_sends_heartbeats(client: TestClient):
    with client.websocket_connect("/api/v1/ws") as ws:
        read_until(ws, EventType.HEARTBEAT)


def test_published_events_reach_a_connected_client(client: TestClient, app: FastAPI):
    from app.websocket.event_bus import get_event_bus

    with client.websocket_connect("/api/v1/ws") as ws:
        read_until(ws, EventType.HEARTBEAT)  # connection is fully established
        portal = client.portal
        portal.call(
            get_event_bus().publish,
            Event.of(EventType.RISK_EVENT, rule="max_daily_loss", decision="REJECTED"),
        )
        message = read_until(ws, EventType.RISK_EVENT)
        assert message["data"]["decision"] == "REJECTED"


def test_subscribe_narrows_the_stream(client: TestClient):
    from app.websocket.event_bus import get_event_bus

    with client.websocket_connect("/api/v1/ws") as ws:
        json.loads(ws.receive_text())  # greeting
        ws.send_text(json.dumps({"action": "subscribe", "events": ["risk_event"]}))
        confirmation = read_until(ws, EventType.SUBSCRIPTION_UPDATED)
        assert confirmation["data"]["events"] == ["risk_event"]

        portal = client.portal
        portal.call(get_event_bus().publish, Event.of(EventType.TICKER_UPDATE, symbol="BTCUSDT"))
        portal.call(get_event_bus().publish, Event.of(EventType.RISK_EVENT, rule="cooldown"))
        message = read_until(ws, EventType.RISK_EVENT)
        assert message["data"]["rule"] == "cooldown"


def test_unknown_event_type_is_rejected_clearly(client: TestClient):
    with client.websocket_connect("/api/v1/ws") as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"action": "subscribe", "events": ["not_a_real_event"]}))
        error = read_until(ws, EventType.ERROR)
        assert error["data"]["code"] == "UNKNOWN_EVENT_TYPE"


def test_malformed_json_does_not_drop_the_connection(client: TestClient):
    with client.websocket_connect("/api/v1/ws") as ws:
        json.loads(ws.receive_text())
        ws.send_text("{not json")
        error = read_until(ws, EventType.ERROR)
        assert error["data"]["code"] == "INVALID_MESSAGE"
        ws.send_text(json.dumps({"action": "pong"}))
        read_until(ws, EventType.HEARTBEAT)


def test_unknown_action_is_reported(client: TestClient):
    with client.websocket_connect("/api/v1/ws") as ws:
        json.loads(ws.receive_text())
        ws.send_text(json.dumps({"action": "trade_now"}))
        error = read_until(ws, EventType.ERROR)
        assert error["data"]["code"] == "UNKNOWN_ACTION"


def test_disconnect_releases_the_connection_slot(client: TestClient):
    from app.websocket.manager import get_connection_manager

    manager = get_connection_manager()
    with client.websocket_connect("/api/v1/ws") as ws:
        json.loads(ws.receive_text())
        assert manager.connection_count == 1
    # The server-side cleanup runs as the socket closes.
    for _ in range(50):
        if manager.connection_count == 0:
            break
        client.portal.call(_sleep)
    assert manager.connection_count == 0


async def _sleep() -> None:
    import asyncio

    await asyncio.sleep(0.02)
