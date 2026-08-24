"""WebSocket connection management (§13).

Handles subscription management, heartbeats, stale-connection detection and
graceful disconnect.  Business logic lives elsewhere; this module only moves
:class:`Event` envelopes onto sockets.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.events import Event, EventType
from app.core.logging_config import get_logger
from app.core.time_utils import utc_now
from app.websocket.event_bus import EventBus, Subscriber

logger = get_logger("websocket.manager")


@dataclass
class Connection:
    websocket: WebSocket
    subscriber: Subscriber
    client_id: str
    connected_at: str = field(default_factory=lambda: utc_now().isoformat())
    last_seen: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class ConnectionManager:
    """Owns the set of live client connections."""

    def __init__(
        self,
        bus: EventBus,
        *,
        heartbeat_interval: float = 20.0,
        client_timeout: float = 60.0,
        max_connections: int = 32,
    ) -> None:
        self._bus = bus
        self._heartbeat_interval = heartbeat_interval
        self._client_timeout = client_timeout
        self._max_connections = max_connections
        self._connections: dict[str, Connection] = {}

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def at_capacity(self) -> bool:
        return len(self._connections) >= self._max_connections

    async def serve(self, websocket: WebSocket, client_id: str) -> None:
        """Run one client connection to completion.

        Three concurrent tasks: outbound event pump, inbound control messages,
        and a heartbeat that also detects stale peers.
        """
        subscriber = Subscriber(self._bus.queue_size, topics=None)
        await self._bus.add(subscriber)
        connection = Connection(websocket=websocket, subscriber=subscriber, client_id=client_id)
        self._connections[client_id] = connection

        await self._send(websocket, Event.of(
            EventType.SYSTEM_STATUS,
            status="connected",
            client_id=client_id,
            heartbeat_interval_seconds=self._heartbeat_interval,
        ))

        tasks = [
            asyncio.create_task(self._pump_outbound(connection), name=f"ws-out-{client_id}"),
            asyncio.create_task(self._read_inbound(connection), name=f"ws-in-{client_id}"),
            asyncio.create_task(self._heartbeat(connection), name=f"ws-hb-{client_id}"),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        finally:
            await self._bus.remove(subscriber)
            self._connections.pop(client_id, None)
            if websocket.client_state is WebSocketState.CONNECTED:
                await websocket.close()
            logger.info(
                "WebSocket client disconnected",
                extra={"event_type": "ws_disconnect", "client_id": client_id},
            )

    async def _pump_outbound(self, connection: Connection) -> None:
        while True:
            event = await connection.subscriber.queue.get()
            if not connection.subscriber.wants(event):
                continue
            await self._send(connection.websocket, event)

    async def _read_inbound(self, connection: Connection) -> None:
        """Handle client control messages: subscribe / unsubscribe / pong."""
        while True:
            raw = await connection.websocket.receive_text()
            connection.last_seen = asyncio.get_event_loop().time()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await self._send(
                    connection.websocket,
                    Event.of(EventType.ERROR, code="INVALID_MESSAGE", message="Malformed JSON."),
                )
                continue
            await self._handle_control(connection, message)

    async def _handle_control(self, connection: Connection, message: dict) -> None:
        action = message.get("action")
        if action == "pong":
            return
        if action in {"subscribe", "unsubscribe"}:
            requested = message.get("events") or []
            valid, invalid = self._parse_topics(requested)
            if invalid:
                await self._send(
                    connection.websocket,
                    Event.of(
                        EventType.ERROR,
                        code="UNKNOWN_EVENT_TYPE",
                        message=f"Unknown event types: {', '.join(sorted(invalid))}",
                    ),
                )
                return
            current = connection.subscriber.topics
            if action == "subscribe":
                connection.subscriber.topics = None if not valid else (current or set()) | valid
            else:
                remaining = (current or set(EventType)) - valid
                connection.subscriber.topics = remaining
            topics = connection.subscriber.topics
            await self._send(
                connection.websocket,
                Event.of(
                    EventType.SUBSCRIPTION_UPDATED,
                    events=sorted(t.value for t in topics) if topics is not None else "all",
                ),
            )
            return
        await self._send(
            connection.websocket,
            Event.of(EventType.ERROR, code="UNKNOWN_ACTION", message=f"Unknown action: {action!r}"),
        )

    @staticmethod
    def _parse_topics(requested: list[str]) -> tuple[set[EventType], set[str]]:
        valid: set[EventType] = set()
        invalid: set[str] = set()
        for name in requested:
            try:
                valid.add(EventType(name))
            except ValueError:
                invalid.add(str(name))
        return valid, invalid

    async def _heartbeat(self, connection: Connection) -> None:
        """Emit periodic heartbeats and close peers that have gone silent."""
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            if loop.time() - connection.last_seen > self._client_timeout:
                logger.warning(
                    "Closing stale WebSocket connection",
                    extra={"event_type": "ws_stale", "client_id": connection.client_id},
                )
                return
            await self._send(
                connection.websocket,
                Event.of(EventType.HEARTBEAT, server_time=utc_now().isoformat()),
            )

    @staticmethod
    async def _send(websocket: WebSocket, event: Event) -> None:
        if websocket.client_state is not WebSocketState.CONNECTED:
            raise WebSocketDisconnect(code=1000)
        await websocket.send_text(event.model_dump_json())


_manager: ConnectionManager | None = None


def init_connection_manager(bus: EventBus, **kwargs: float | int) -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager(bus, **kwargs)  # type: ignore[arg-type]
    return _manager


def get_connection_manager() -> ConnectionManager:
    if _manager is None:
        raise RuntimeError("Connection manager is not initialised.")
    return _manager


def reset_connection_manager() -> None:
    global _manager
    _manager = None
