"""Risk namespace: current state, active limits, decision history (§31, §59).

Read-only by design. The risk engine enforces limits; it does not own their
values, so there is deliberately no endpoint here that changes one -- that
belongs to Settings, where it is subject to the same validation as every
other configuration change (§64).
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.v1.deps import SessionDep, SettingsDep
from app.core.time_utils import utc_now
from app.models.enums import EngineState, RiskDecision
from app.models.trading import RiskEvent
from app.risk.engine import RiskEngine, SystemState
from app.schemas.risk import RiskEventOut, RiskParametersOut, RiskStateOut

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/parameters", response_model=RiskParametersOut, summary="Active risk limits")
async def parameters(settings: SettingsDep) -> RiskParametersOut:
    risk = settings.risk
    return RiskParametersOut(
        **{
            key: (value if isinstance(value, int | bool) else float(value))
            for key, value in risk.model_dump().items()
        }
    )


@router.get("/state", response_model=RiskStateOut, summary="Is trading currently permitted?")
async def state(request_settings: SettingsDep, session: SessionDep) -> RiskStateOut:
    """Evaluate only the account/system halts -- the conditions that stop all
    trading regardless of any particular trade.

    Per-trade rules (spread, sizing, cooldown) are deliberately not evaluated
    here: they need a concrete trade to be meaningful, and reporting them in
    a global "is trading permitted" view would be misleading.
    """
    from app.services.app_state import load_application_state

    engine = RiskEngine(request_settings.risk)
    app_state = await load_application_state(session, request_settings)
    engine_state = app_state["engine_state"]

    # Account-level halts (daily loss, drawdown, loss streak) need real
    # portfolio figures, which arrive with the paper trading engine (Phase
    # 11).  Only the system-health gates are evaluated here; reporting a
    # fabricated equity would be worse than reporting none (§96).
    system = SystemState(engine_state=engine_state)
    halt = engine.check_system_health(system)
    if halt is None and engine_state is EngineState.RUNNING:
        return RiskStateOut(
            trading_permitted=True,
            decision=RiskDecision.APPROVED.value,
            rule=None,
            reason=None,
            engine_state=engine_state.value,
            checked_at=utc_now(),
        )

    reason = halt.reason if halt else "The trading engine is not running."
    rule = halt.rule if halt else "engine_paused"
    return RiskStateOut(
        trading_permitted=False,
        decision=RiskDecision.PAUSED.value,
        rule=rule,
        reason=reason,
        engine_state=engine_state.value,
        checked_at=utc_now(),
    )


@router.get("/events", response_model=list[RiskEventOut], summary="Risk decision history")
async def events(
    session: SessionDep,
    symbol: str | None = Query(None),
    decision: str | None = Query(None, description="REJECTED or PAUSED"),
    limit: int = Query(100, ge=1, le=500),
) -> list[RiskEventOut]:
    query = select(RiskEvent).order_by(RiskEvent.timestamp.desc()).limit(limit)
    if symbol:
        query = query.where(RiskEvent.symbol == symbol.upper())
    if decision:
        query = query.where(RiskEvent.decision == decision.upper())
    rows = (await session.execute(query)).scalars().all()
    return [
        RiskEventOut(
            id=row.id,
            timestamp=row.timestamp,
            venue=row.venue,
            symbol=row.symbol,
            decision=row.decision,
            rule=row.rule,
            reason=row.reason,
            details=row.details,
        )
        for row in rows
    ]
