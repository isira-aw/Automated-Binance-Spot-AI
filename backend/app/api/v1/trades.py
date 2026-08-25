"""Trades namespace: the closed round-trip ledger (§41, §59).

Replaces the ``trades`` entry in ``not_implemented.py`` now that Phase 15b
gives paper trading somewhere to write a closed trade. Shared by every venue
(§41: one metric definition, computed the same way regardless of where a
trade happened) -- ``venue`` filters to ``PAPER``, ``LIVE``, or the backtest
ledger is its own separate namespace (``backtests/{id}``) since a backtest
run's trades belong to that specific run, not a shared account ledger.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.v1.deps import SessionDep
from app.models.trading import Trade
from app.schemas.paper_trading import TradeOut

router = APIRouter(prefix="/trades", tags=["trades"])


def _to_out(row: Trade) -> TradeOut:
    return TradeOut(
        id=row.id,
        venue=row.venue,
        symbol=row.symbol,
        position_id=row.position_id,
        signal_id=row.signal_id,
        side=row.side,
        quantity=float(row.quantity),
        entry_price=float(row.entry_price),
        exit_price=float(row.exit_price),
        entry_time=row.entry_time,
        exit_time=row.exit_time,
        gross_pnl=float(row.gross_pnl),
        fees=float(row.fees),
        slippage_cost=float(row.slippage_cost),
        net_pnl=float(row.net_pnl),
        return_pct=float(row.return_pct),
        mae=float(row.mae) if row.mae is not None else None,
        mfe=float(row.mfe) if row.mfe is not None else None,
        exit_reason=row.exit_reason,
        strategy_version=row.strategy_version,
        model_version=row.model_version,
    )


@router.get("", response_model=list[TradeOut], summary="Closed trade ledger")
async def list_trades(
    session: SessionDep,
    venue: str = Query("PAPER"),
    symbol: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[TradeOut]:
    query = select(Trade).where(Trade.venue == venue.upper()).order_by(Trade.exit_time.desc())
    if symbol:
        query = query.where(Trade.symbol == symbol.upper())
    rows = (await session.execute(query.limit(limit))).scalars().all()
    return [_to_out(row) for row in rows]
