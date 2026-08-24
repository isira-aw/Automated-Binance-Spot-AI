"""Fixtures for API-level tests.

These exercise the real application (routers, middleware, error envelope,
WebSocket manager) but replace the startup sequence, so they need no
PostgreSQL, Redis, or Binance connection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from tests.conftest import make_settings


@pytest.fixture
def app() -> Iterator[FastAPI]:
    from app.api.app_factory import create_app
    from app.models.enums import ComponentHealth
    from app.monitoring.health import init_health_service
    from app.websocket.event_bus import init_event_bus, reset_event_bus
    from app.websocket.manager import init_connection_manager, reset_connection_manager

    settings = make_settings(env="testing", cors_allow_origins=["http://localhost:5173"])
    reset_event_bus()
    reset_connection_manager()
    application = create_app(settings)

    @asynccontextmanager
    async def test_lifespan(_: FastAPI) -> AsyncIterator[None]:
        bus = init_event_bus(settings.websocket.outbound_queue_size)
        init_connection_manager(
            bus,
            heartbeat_interval=0.05,
            client_timeout=5.0,
            max_connections=settings.websocket.max_connections,
        )
        service = init_health_service(settings)
        service.register_static("backend", ComponentHealth.ONLINE)
        service.register_static("database", ComponentHealth.ONLINE)
        service.register_static("redis", ComponentHealth.ONLINE)
        service.register_static("binance", ComponentHealth.NOT_IMPLEMENTED, "Not built yet.")
        service.register_static("claude", ComponentHealth.DISABLED, "Tier 2 component.")
        yield

    application.router.lifespan_context = test_lifespan
    yield application
    reset_event_bus()
    reset_connection_manager()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
