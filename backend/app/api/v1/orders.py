"""Orders namespace: paper order history and manual entry (§11B, §31, §59).

Replaces the ``orders`` entry in ``not_implemented.py`` now that Phase 15b
wires the Phase 11 simulator to persistence. ``POST /orders`` places a
paper trade -- manual only (see app/paper_trading/account.py's module
docstring for why nothing here is triggered automatically by a signal).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.v1.deps import SessionDep, SettingsDep
from app.core.errors import RiskLimitExceeded
from app.models.trading import PaperOrder
from app.paper_trading.account import open_paper_trade
from app.schemas.paper_trading import OpenOrderRequest, PaperOrderOut

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_out(row: PaperOrder) -> PaperOrderOut:
    return PaperOrderOut(
        id=row.id,
        client_order_id=row.client_order_id,
        signal_id=row.signal_id,
        symbol=row.symbol,
        side=row.side,
        order_type=row.order_type,
        status=row.status,
        quantity=float(row.quantity),
        price=float(row.price) if row.price is not None else None,
        filled_quantity=float(row.filled_quantity),
        average_fill_price=float(row.average_fill_price)
        if row.average_fill_price is not None
        else None,
        fee=float(row.fee),
        submitted_at=row.submitted_at,
        strategy_version=row.strategy_version,
    )


@router.get("", response_model=list[PaperOrderOut], summary="Paper order history")
async def list_orders(session: SessionDep, limit: int = 100) -> list[PaperOrderOut]:
    rows = (
        await session.execute(
            select(PaperOrder).order_by(PaperOrder.submitted_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [_to_out(row) for row in rows]


@router.post("", response_model=PaperOrderOut, status_code=201, summary="Place a paper order")
async def place_order(
    request: Request, body: OpenOrderRequest, session: SessionDep, settings: SettingsDep
) -> PaperOrderOut:
    """Approved -> the filled order. Rejected -> 409, with the reason and
    rule (also persisted to ``risk_events``, visible at ``GET /risk/events``).
    """
    binance_service = getattr(request.app.state, "binance", None)
    result = await open_paper_trade(
        session,
        settings,
        binance_service,
        symbol=body.symbol.upper(),
        stop_price=Decimal(str(body.stop_price)),
        take_profit=Decimal(str(body.take_profit)) if body.take_profit is not None else None,
        trailing_distance=Decimal(str(body.trailing_distance))
        if body.trailing_distance is not None
        else None,
        signal_id=body.signal_id,
    )
    if not result.approved or result.order is None:
        raise RiskLimitExceeded(
            result.rejection_reason or "Rejected by the risk engine.",
            metadata={"rule": result.rejection_rule, "symbol": body.symbol.upper()},
        )
    return _to_out(result.order)
