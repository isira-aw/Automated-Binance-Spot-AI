"""WebSocket endpoint (§13)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, WebSocket, status

from app.core.logging_config import get_logger
from app.websocket.manager import get_connection_manager

logger = get_logger("api.websocket")

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Stream structured events to a connected client.

    Clients may send ``{"action": "subscribe", "events": [...]}`` (or
    ``unsubscribe``) to narrow the stream, and ``{"action": "pong"}`` in reply
    to heartbeats.  Without any subscribe message a client receives all events.
    """
    manager = get_connection_manager()
    if manager.at_capacity():
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    await websocket.accept()
    client_id = uuid4().hex
    logger.info(
        "WebSocket client connected",
        extra={"event_type": "ws_connect", "client_id": client_id},
    )
    await manager.serve(websocket, client_id)
