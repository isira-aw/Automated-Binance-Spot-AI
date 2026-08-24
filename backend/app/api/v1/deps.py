"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.binance.service import BinanceService
from app.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError
from app.database.session import get_db
from app.monitoring.health import HealthService, get_health_service
from app.websocket.event_bus import EventBus, get_event_bus

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]
HealthDep = Annotated[HealthService, Depends(get_health_service)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


def get_binance_service(request: Request) -> BinanceService:
    """The live BinanceService, or a clear error if it never connected.

    Endpoints that only read already-persisted market data (coverage,
    candles, integrity reports) do not depend on this -- only endpoints that
    need to call the exchange directly, such as triggering a backfill, do.
    """
    service = getattr(request.app.state, "binance", None)
    if service is None:
        raise ServiceUnavailableError("Binance service is not initialised.")
    return service


BinanceServiceDep = Annotated[BinanceService, Depends(get_binance_service)]
