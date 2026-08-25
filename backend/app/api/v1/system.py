"""System endpoints: health, version, state, tier status (§43, §105)."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.v1.deps import HealthDep, SessionDep, SettingsDep
from app.database.session import alembic_revision
from app.ml.registry import verify_registry_artifacts
from app.models.enums import ComponentHealth
from app.schemas.system import HealthOut, SystemStateOut, TierStatusOut, VersionOut
from app.services.app_state import load_application_state

router = APIRouter(prefix="/system", tags=["system"])

# Components built in Tier 1 vs. those reserved for Tier 2 (§1a).
TIER1_COMPONENTS = [
    "market_data",
    "technical_analysis",
    "market_structure",
    "lightgbm",
    "risk_engine",
    "paper_trading",
    "backtesting",
    "signal_fusion",
]
TIER2_COMPONENTS = [
    "patterns",
    "market_regime",
    "transformer",
    "ensemble",
    "news",
    "fundamentals",
    "ollama",
    "claude",
]

# Components that actually feed a generated signal today (§14).
#
# Kept accurate in both directions: it was `[]` through Phase 12 because no
# fusion engine existed, and understating it now that Phase 13 fuses these
# two would be its own kind of dishonesty. Every entry here must correspond
# to a `SignalComponent` row a real signal carries -- see
# `app/signals/service.py`, which builds exactly these two.
#
# Note what this does *not* claim: a signal influencing a *trade*. Nothing
# executes automatically (Phase 15b is manual-only), which the health
# endpoint reports separately as `trading_engine: NOT_IMPLEMENTED`.
INFLUENCING_SIGNALS = ["technical_analysis", "market_structure", "lightgbm"]


@router.get("/health", response_model=HealthOut, summary="Component health")
async def health(service: HealthDep, response: Response) -> HealthOut:
    """Aggregated component health.

    Returns HTTP 503 when any expected component is not healthy, so container
    health checks and the frontend agree on a single definition of "up".
    """
    report = await service.check()
    if not report.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(**report.to_dict())


@router.get("/version", response_model=VersionOut, summary="Build and schema version")
async def version(settings: SettingsDep, session: SessionDep) -> VersionOut:
    try:
        revision = await alembic_revision(session)
    except Exception:
        revision = None
    return VersionOut(
        app_name=settings.app_name,
        environment=settings.env.value,
        strategy_version=settings.models.strategy_version,
        feature_version=settings.models.feature_version,
        schema_revision=revision,
    )


@router.get("/state", response_model=SystemStateOut, summary="Persisted runtime state")
async def state(settings: SettingsDep, session: SessionDep) -> SystemStateOut:
    persisted = await load_application_state(session, settings)
    integrity = await verify_registry_artifacts(session, settings)
    return SystemStateOut(
        mode=persisted["mode"].value,
        engine_state=persisted["engine_state"],
        live_armed=persisted["live_armed"],
        live_trading_enabled=persisted["live_trading_enabled"],
        last_shutdown_at=persisted["last_shutdown_at"],
        model_registry_ok=integrity.ok,
        model_registry_problems=[
            {
                "model_id": problem.model_id,
                "version": problem.version,
                "status": problem.status,
                "reason": problem.reason,
            }
            for problem in integrity.problems
        ],
    )


@router.get("/tiers", response_model=TierStatusOut, summary="Capability tier status")
async def tiers(settings: SettingsDep) -> TierStatusOut:
    """Which components exist and which of them influence live signals (§14)."""
    enabled = {
        "patterns": False,
        "market_regime": False,
        "transformer": settings.models.transformer_enabled,
        "ensemble": settings.models.ensemble_enabled,
        "news": settings.news.enabled,
        "fundamentals": settings.news.enabled,
        "ollama": settings.llm.ollama_enabled,
        "claude": settings.llm.claude_enabled,
    }
    return TierStatusOut(
        tier1_components=TIER1_COMPONENTS,
        tier2_components=TIER2_COMPONENTS,
        tier2_enabled=enabled,
        influencing_signals=INFLUENCING_SIGNALS,
    )


@router.get("/ping", summary="Liveness probe")
async def ping() -> dict[str, str]:
    return {"status": ComponentHealth.ONLINE.value.lower()}
