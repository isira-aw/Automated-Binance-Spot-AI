"""Backtests namespace: run and inspect backtests (§35, §41, §82, §59).

Replaces the ``backtests`` entry in ``not_implemented.py`` now that Phase 15
wires the Phase 12 engine to persistence and a REST surface. Literal-path
routes are registered before dynamic ones, per the Phase 9 route-ordering
lesson.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.v1.deps import SessionDep, SettingsDep
from app.backtesting.service import run_backtest
from app.core.errors import NotFoundError
from app.models.backtesting import BacktestRun
from app.schemas.backtests import BacktestRunOut, BacktestRunRequest, BacktestRunSummaryOut

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _to_out(run: BacktestRun) -> BacktestRunOut:
    return BacktestRunOut(
        id=run.id,
        job_id=run.job_id,
        status=run.status,
        symbols=run.symbols,
        timeframe=run.timeframe,
        range_start=run.range_start,
        range_end=run.range_end,
        initial_capital=float(run.initial_capital),
        maker_fee=float(run.maker_fee),
        taker_fee=float(run.taker_fee),
        slippage_bps=float(run.slippage_bps),
        strategy_version=run.strategy_version,
        feature_version=run.feature_version,
        config=run.config,
        metrics=run.metrics,
        assumptions=run.assumptions,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        created_at=run.created_at,
        trades=[
            {
                "symbol": trade.symbol,
                "side": trade.side,
                "quantity": float(trade.quantity),
                "entry_time": trade.entry_time,
                "entry_price": float(trade.entry_price),
                "exit_time": trade.exit_time,
                "exit_price": float(trade.exit_price),
                "gross_pnl": float(trade.gross_pnl),
                "fees": float(trade.fees),
                "slippage_cost": float(trade.slippage_cost),
                "net_pnl": float(trade.net_pnl),
                "return_pct": float(trade.return_pct),
                "mae": float(trade.mae) if trade.mae is not None else None,
                "mfe": float(trade.mfe) if trade.mfe is not None else None,
                "exit_reason": trade.exit_reason,
            }
            for trade in run.trades
        ],
    )


def _to_summary(run: BacktestRun) -> BacktestRunSummaryOut:
    return BacktestRunSummaryOut(
        id=run.id,
        job_id=run.job_id,
        status=run.status,
        symbols=run.symbols,
        timeframe=run.timeframe,
        range_start=run.range_start,
        range_end=run.range_end,
        strategy_version=run.strategy_version,
        metrics=run.metrics,
        created_at=run.created_at,
    )


@router.get("", response_model=list[BacktestRunSummaryOut], summary="Recent backtest runs")
async def list_backtests(session: SessionDep) -> list[BacktestRunSummaryOut]:
    rows = (
        await session.execute(select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(50))
    ).scalars().all()
    return [_to_summary(row) for row in rows]


@router.post("/run", response_model=BacktestRunOut, status_code=201, summary="Run a backtest")
async def run(
    request: Request, body: BacktestRunRequest, session: SessionDep, settings: SettingsDep
) -> BacktestRunOut:
    binance_service = getattr(request.app.state, "binance", None)
    run_row = await run_backtest(
        session,
        settings,
        symbol=body.symbol.upper(),
        timeframe=body.timeframe,
        range_start=body.range_start,
        range_end=body.range_end,
        binance_service=binance_service,
    )
    return _to_out(run_row)


@router.get("/{run_id}", response_model=BacktestRunOut, summary="One backtest run's full result")
async def get_backtest(run_id: int, session: SessionDep) -> BacktestRunOut:
    row = (
        await session.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"No backtest run with id={run_id}.", metadata={"run_id": run_id})
    return _to_out(row)
