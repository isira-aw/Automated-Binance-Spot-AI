"""Aggregate v1 API router (§59)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import market, models, not_implemented, risk, settings, signals, system

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(market.router)
api_router.include_router(models.router)
api_router.include_router(risk.router)
api_router.include_router(signals.router)
api_router.include_router(settings.router)
api_router.include_router(not_implemented.build_router())
