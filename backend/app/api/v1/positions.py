"""Positions namespace: open paper positions and manual exit (§11B, §31, §59).

Replaces the ``positions`` entry in ``not_implemented.py`` now that Phase 15b
wires the Phase 11 simulator to persistence.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.v1.deps import SessionDep, SettingsDep
from app.models.enums import PositionStatus
from app.models.trading import PaperPosition
from app.paper_trading.account import close_paper_trade
from app.schemas.paper_trading import PaperPositionOut

router = APIRouter(prefix="/positions", tags=["positions"])


def _to_out(row: PaperPosition) -> PaperPositionOut:
    return PaperPositionOut(
        id=row.id,
        symbol=row.symbol,
        status=row.status,
        quantity=float(row.quantity),
        entry_price=float(row.entry_price),
        entry_time=row.entry_time,
        exit_price=float(row.exit_price) if row.exit_price is not None else None,
        exit_time=row.exit_time,
        stop_loss=float(row.stop_loss) if row.stop_loss is not None else None,
        take_profit=float(row.take_profit) if row.take_profit is not None else None,
        trailing_stop=float(row.trailing_stop) if row.trailing_stop is not None else None,
        unrealised_pnl=float(row.unrealised_pnl) if row.unrealised_pnl is not None else None,
        realised_pnl=float(row.realised_pnl) if row.realised_pnl is not None else None,
        fees_paid=float(row.fees_paid),
        signal_id=row.signal_id,
        strategy_version=row.strategy_version,
    )


@router.get("", response_model=list[PaperPositionOut], summary="Open paper positions")
async def list_positions(session: SessionDep) -> list[PaperPositionOut]:
    rows = (
        await session.execute(
            select(PaperPosition)
            .where(PaperPosition.status == PositionStatus.OPEN.value)
            .order_by(PaperPosition.entry_time.desc())
        )
    ).scalars().all()
    return [_to_out(row) for row in rows]


@router.post(
    "/{symbol}/close", response_model=PaperPositionOut, summary="Close an open paper position"
)
async def close_position(
    symbol: str, request: Request, session: SessionDep, settings: SettingsDep
) -> PaperPositionOut:
    binance_service = getattr(request.app.state, "binance", None)
    row = await close_paper_trade(session, settings, binance_service, symbol=symbol.upper())
    return _to_out(row)
