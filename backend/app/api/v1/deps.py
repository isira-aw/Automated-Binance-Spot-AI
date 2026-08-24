"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database.session import get_db
from app.monitoring.health import HealthService, get_health_service
from app.websocket.event_bus import EventBus, get_event_bus

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]
HealthDep = Annotated[HealthService, Depends(get_health_service)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
