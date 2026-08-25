"""Explicit `NOT IMPLEMENTED` routes for unbuilt phases (§59, §96).

The API surface from §59 is registered from day one so the frontend contract is
stable and OpenAPI documents the whole namespace — but every route that has no
engine behind it returns HTTP 501 with ``code: "NOT_IMPLEMENTED"``.  The system
never returns randomized placeholder data in place of a real feature.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import NotImplementedYetError

# namespace -> (tier, the MVP/Tier-1 phase that will implement it)
PENDING_NAMESPACES: dict[str, tuple[str, str]] = {
    "orders": ("TIER_1", "Phase 11: internal paper trading simulator"),
    "positions": ("TIER_1", "Phase 11: internal paper trading simulator"),
    "trades": ("TIER_1", "Phase 11: internal paper trading simulator"),
    "paper-trading": ("TIER_1", "Phase 11: internal paper trading simulator"),
    "binance": ("TIER_1", "Phase 5: Binance connector"),
    "training": ("TIER_2", "Phase 28: model registry and retraining"),
    "patterns": ("TIER_2", "Phase 21: pattern engine"),
    "news": ("TIER_2", "Phase 25: news/fundamental engine"),
    "fundamentals": ("TIER_2", "Phase 25: news/fundamental engine"),
}


def build_router() -> APIRouter:
    router = APIRouter()
    for namespace, (tier, phase) in PENDING_NAMESPACES.items():
        router.include_router(_namespace_router(namespace, tier, phase))
    return router


def _namespace_router(namespace: str, tier: str, phase: str) -> APIRouter:
    sub = APIRouter(prefix=f"/{namespace}", tags=[namespace])

    @sub.get(
        "",
        summary=f"NOT IMPLEMENTED — {namespace}",
        description=(
            f"Not implemented yet. Planned in **{tier}**, {phase}. "
            "This endpoint intentionally returns 501 rather than placeholder data."
        ),
        status_code=501,
    )
    async def _pending() -> None:
        raise NotImplementedYetError(
            f"The '{namespace}' API is not implemented yet ({phase}).",
            metadata={"namespace": namespace, "tier": tier, "planned_phase": phase},
        )

    return sub
