"""Aggregate v1 API router (§59)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    backtests,
    market,
    models,
    not_implemented,
    orders,
    positions,
    risk,
    settings,
    signals,
    system,
    trades,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(market.router)
api_router.include_router(models.router)
api_router.include_router(risk.router)
api_router.include_router(signals.router)
api_router.include_router(backtests.router)
api_router.include_router(orders.router)
api_router.include_router(positions.router)
api_router.include_router(trades.router)
api_router.include_router(settings.router)
api_router.include_router(not_implemented.build_router())
