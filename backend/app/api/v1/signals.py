"""Signal fusion namespace: read persisted signals, trigger fusion (§30, §59).

Replaces the ``signals`` entry in ``not_implemented.py`` now that Phase 13
builds the technical + LightGBM fusion pipeline. Literal-path routes
(``/signals/generate``) are registered before the dynamic ``/signals/{id}``
route -- Phase 9 found that FastAPI/Starlette otherwise lets the dynamic
route shadow a literal one with the same segment count.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.v1.deps import SessionDep, SettingsDep
from app.core.errors import NotFoundError
from app.core.logging_config import get_logger
from app.models.trading import Signal
from app.schemas.signals import GenerateSignalRequest, SignalOut
from app.signals.service import generate_signal

logger = get_logger("api.signals")
router = APIRouter(prefix="/signals", tags=["signals"])


def _to_out(row: Signal) -> SignalOut:
    return SignalOut(
        id=row.id,
        symbol=row.symbol,
        timeframe=row.timeframe,
        open_time=row.open_time,
        generated_at=row.generated_at,
        action=row.action,
        score=float(row.score),
        confidence=float(row.confidence),
        reason_codes=row.reason_codes,
        strategy_version=row.strategy_version,
        fusion_method=row.fusion_method,
        reference_price=float(row.reference_price) if row.reference_price is not None else None,
        risk_decision=row.risk_decision,
        risk_reason=row.risk_reason,
        venue=row.venue,
        components=[
            {
                "kind": c.kind,
                "score": float(c.score),
                "weight": float(c.weight),
                "confidence": float(c.confidence) if c.confidence is not None else None,
                "version": c.version,
                "active": c.active,
                "details": c.details,
            }
            for c in row.components
        ],
    )


@router.get("", response_model=list[SignalOut], summary="List persisted signals")
async def list_signals(
    session: SessionDep,
    symbol: str | None = Query(None),
    timeframe: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> list[SignalOut]:
    query = select(Signal).order_by(Signal.generated_at.desc()).limit(limit)
    if symbol:
        query = query.where(Signal.symbol == symbol.upper())
    if timeframe:
        query = query.where(Signal.timeframe == timeframe)
    rows = (await session.execute(query)).scalars().all()
    return [_to_out(row) for row in rows]


@router.get(
    "/latest", response_model=SignalOut | None, summary="Latest signal for a symbol/timeframe"
)
async def latest_signal(
    session: SessionDep,
    symbol: str = Query(...),
    timeframe: str = Query(...),
) -> SignalOut | None:
    row = (
        await session.execute(
            select(Signal)
            .where(Signal.symbol == symbol.upper(), Signal.timeframe == timeframe)
            .order_by(Signal.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _to_out(row)


@router.post("/generate", response_model=SignalOut, summary="Fuse and persist a signal")
async def generate(
    request: GenerateSignalRequest, session: SessionDep, settings: SettingsDep
) -> SignalOut:
    signal = await generate_signal(
        session, settings, symbol=request.symbol.upper(), timeframe=request.timeframe
    )
    if signal is None:
        raise NotFoundError(
            "No technical features are available yet to anchor a signal to "
            f"for {request.symbol.upper()}/{request.timeframe}.",
            metadata={"symbol": request.symbol.upper(), "timeframe": request.timeframe},
        )
    return _to_out(signal)
