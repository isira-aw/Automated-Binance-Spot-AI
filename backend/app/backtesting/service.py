"""Orchestrates a backtest run against persisted history and persists the result (§35, §82).

The reference strategy fused here is technical-only (§30's `TECHNICAL`
component) -- there is no per-bar LightGBM inference path yet, unlike live
signal generation (Phase 13), which only ever predicts against the *latest*
bar. Extending backtesting to include LightGBM is deferred rather than
built as a shortcut that risks silently leaking a live-inference assumption
into a historical replay.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtesting.engine import BacktestEngine, HistoricalBar, StrategyDecision
from app.binance.filters import resolve_symbol_filters
from app.config import Settings
from app.core.errors import ValidationError
from app.core.logging_config import get_logger
from app.models.backtesting import BacktestRun, BacktestTrade
from app.models.enums import SignalAction, SignalComponentKind
from app.models.market import Candle, TechnicalFeature
from app.signals.fusion import ComponentScore, fuse
from app.signals.technical_score import TECHNICAL_SCORE_VERSION, compute_technical_score

if TYPE_CHECKING:
    from app.binance.service import BinanceService

logger = get_logger("backtesting.service")


async def _load_bars(
    session: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    range_start: datetime,
    range_end: datetime,
) -> list[Candle]:
    rows = (
        await session.execute(
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.is_closed.is_(True),
                Candle.open_time >= range_start,
                Candle.open_time <= range_end,
            )
            .order_by(Candle.open_time.asc())
        )
    ).scalars().all()
    return rows


async def _load_features(
    session: AsyncSession, *, symbol: str, timeframe: str, feature_version: str,
    range_start: datetime, range_end: datetime,
) -> dict[datetime, dict]:
    rows = (
        await session.execute(
            select(TechnicalFeature)
            .where(
                TechnicalFeature.symbol == symbol,
                TechnicalFeature.timeframe == timeframe,
                TechnicalFeature.feature_version == feature_version,
                TechnicalFeature.open_time >= range_start,
                TechnicalFeature.open_time <= range_end,
            )
        )
    ).scalars().all()
    return {row.open_time: row.features for row in rows}


def _make_strategy(
    features_by_time: dict[datetime, dict],
    *,
    min_confidence: float,
    action_margin: float,
    atr_stop_multiplier: Decimal,
    atr_reward_multiplier: Decimal,
):
    def strategy(bars):
        last = bars[-1]
        raw_features = features_by_time.get(last.timestamp)
        if raw_features is None:
            return None

        score, confidence, details = compute_technical_score(raw_features)
        component = ComponentScore(
            kind=SignalComponentKind.TECHNICAL,
            score=score,
            weight=1.0,
            confidence=confidence,
            version=TECHNICAL_SCORE_VERSION,
            active=True,
            details=details,
        )
        result = fuse([component], min_confidence=min_confidence, action_margin=action_margin)
        reason = ",".join(result.reason_codes)

        if result.action == SignalAction.BUY:
            atr = raw_features.get("atr_14")
            if atr is None:
                return None
            atr_dec = Decimal(str(atr))
            if atr_dec <= 0:
                return None
            stop_price = last.close - atr_dec * atr_stop_multiplier
            if stop_price <= 0:
                return None
            take_profit = last.close + atr_dec * atr_reward_multiplier
            return StrategyDecision(
                action="BUY", stop_price=stop_price, take_profit=take_profit, reason=reason
            )

        # Spot-only: no shorting (§56). A SELL/EXIT-leaning fused score can
        # only ever close an existing long, never open a short.
        if result.action in (SignalAction.SELL, SignalAction.EXIT):
            return StrategyDecision(action="EXIT", reason=reason)

        return None

    return strategy


async def run_backtest(
    session: AsyncSession,
    settings: Settings,
    *,
    symbol: str,
    timeframe: str,
    range_start: datetime,
    range_end: datetime,
    binance_service: BinanceService | None = None,
) -> BacktestRun:
    if range_end <= range_start:
        raise ValidationError("range_end must be after range_start.")

    candles = await _load_bars(
        session, symbol=symbol, timeframe=timeframe, range_start=range_start, range_end=range_end
    )
    if len(candles) < 2:
        raise ValidationError(
            f"Not enough closed candles for {symbol}/{timeframe} in the requested range "
            "to run a backtest (need at least 2).",
            metadata={"symbol": symbol, "timeframe": timeframe, "candle_count": len(candles)},
        )
    if len(candles) > settings.backtesting.max_bars:
        raise ValidationError(
            f"Requested range has {len(candles)} candles, over the {settings.backtesting.max_bars} "
            "bar cap for a single backtest run. Narrow the range.",
            metadata={"candle_count": len(candles), "max_bars": settings.backtesting.max_bars},
        )

    features_by_time = await _load_features(
        session,
        symbol=symbol,
        timeframe=timeframe,
        feature_version=settings.models.feature_version,
        range_start=range_start,
        range_end=range_end,
    )

    filters, filters_source = resolve_symbol_filters(binance_service, symbol)

    bars = [
        HistoricalBar(
            timestamp=row.open_time,
            open=Decimal(str(row.open)),
            high=Decimal(str(row.high)),
            low=Decimal(str(row.low)),
            close=Decimal(str(row.close)),
            volume=Decimal(str(row.volume)),
        )
        for row in candles
    ]

    bt = settings.backtesting
    initial_capital = Decimal(str(bt.initial_capital))
    fee_rate = Decimal(str(bt.taker_fee))
    slippage_bps = Decimal(str(bt.slippage_bps))

    engine = BacktestEngine(
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=initial_capital,
        risk=settings.risk,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        filters=filters,
    )
    strategy = _make_strategy(
        features_by_time,
        min_confidence=settings.models.fusion_min_confidence,
        action_margin=settings.models.fusion_action_margin,
        atr_stop_multiplier=Decimal(str(bt.atr_stop_multiplier)),
        atr_reward_multiplier=Decimal(str(bt.atr_reward_multiplier)),
    )

    job_id = uuid.uuid4().hex
    started_at = _now()
    try:
        result = engine.run(bars, strategy)
    except Exception as exc:
        run = BacktestRun(
            job_id=job_id,
            status="FAILED",
            symbols=[symbol],
            timeframe=timeframe,
            range_start=range_start,
            range_end=range_end,
            initial_capital=initial_capital,
            maker_fee=Decimal(str(bt.maker_fee)),
            taker_fee=fee_rate,
            slippage_bps=slippage_bps,
            strategy_version=settings.models.strategy_version,
            started_at=started_at,
            finished_at=_now(),
            error=str(exc),
        )
        session.add(run)
        await session.commit()
        logger.error(
            "Backtest run failed",
            extra={"event_type": "backtest_failed", "symbol": symbol, "timeframe": timeframe},
            exc_info=exc,
        )
        raise

    assumptions = result.assumptions.to_dict()
    assumptions["filters_source"] = filters_source

    run = BacktestRun(
        job_id=job_id,
        status="COMPLETED",
        symbols=[symbol],
        timeframe=timeframe,
        range_start=range_start,
        range_end=range_end,
        initial_capital=initial_capital,
        maker_fee=Decimal(str(bt.maker_fee)),
        taker_fee=fee_rate,
        slippage_bps=slippage_bps,
        strategy_version=settings.models.strategy_version,
        feature_version=settings.models.feature_version,
        config={
            "atr_stop_multiplier": bt.atr_stop_multiplier,
            "atr_reward_multiplier": bt.atr_reward_multiplier,
            "fusion_min_confidence": settings.models.fusion_min_confidence,
            "fusion_action_margin": settings.models.fusion_action_margin,
        },
        metrics=result.metrics.to_dict(),
        assumptions=assumptions,
        started_at=started_at,
        finished_at=_now(),
    )
    run.trades = [
        BacktestTrade(
            symbol=trade.symbol,
            side="BUY",
            quantity=trade.quantity,
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            exit_time=trade.exit_time,
            exit_price=trade.exit_price,
            gross_pnl=trade.gross_pnl,
            fees=trade.fees,
            slippage_cost=trade.slippage_cost,
            net_pnl=trade.net_pnl,
            return_pct=trade.return_pct,
            mae=trade.mae,
            mfe=trade.mfe,
            exit_reason=trade.exit_reason,
        )
        for trade in result.trades
    ]
    session.add(run)
    await session.commit()
    await session.refresh(run, attribute_names=["trades"])

    logger.info(
        "Backtest run persisted",
        extra={
            "event_type": "backtest_persisted",
            "job_id": job_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "trade_count": len(run.trades),
        },
    )
    return run


def _now() -> datetime:
    from app.core.time_utils import utc_now

    return utc_now()
