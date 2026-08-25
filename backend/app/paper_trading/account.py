"""Wires the Phase 11 simulator to persistence: the execution entrypoint that
never existed (§11B, §31, §41).

Phase 11 built ``PaperTradingEngine``/``Portfolio`` as a pure in-memory
library, reused as-is by backtesting (Phase 12). Nothing before this module
ever called it outside a backtest run, so ``paper_orders``/``paper_positions``
(Phase 2 schema) never had a row written to them. This module is that
missing piece: it rehydrates a ``Portfolio`` from persisted state before
every action and persists the result after, so a paper account survives
across requests and process restarts the same way a real one would.

Manual entry only. Nothing here is triggered automatically by a generated
Signal -- that is a deliberate, disclosed scope boundary (see
PROJECT_STATUS.md), not an oversight: autonomous order placement, even in
paper mode, needs its own explicit policy decision before it exists.

Every entry still routes through the risk engine exactly as backtesting
does (§31) -- this module adds persistence around ``PaperTradingEngine``,
it does not reimplement or bypass any of its authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.binance.filters import resolve_symbol_filters
from app.config import Settings
from app.core.errors import ServiceUnavailableError, ValidationError
from app.core.logging_config import get_logger
from app.core.time_utils import utc_now
from app.models.enums import OrderSide, OrderStatus, OrderType, PositionStatus
from app.models.trading import PaperOrder, PaperPosition, PortfolioSnapshot, Trade
from app.paper_trading.fills import exit_reason_for_bar, update_trailing_stop
from app.paper_trading.portfolio import ClosedTrade, OpenPosition, Portfolio
from app.paper_trading.simulator import PaperTradingEngine, SimulatorConfig
from app.risk.engine import RiskEngine, SystemState
from app.risk.events import record_risk_event

if TYPE_CHECKING:
    from app.binance.service import BinanceService

logger = get_logger("paper_trading.account")

VENUE = "PAPER"


@dataclass
class OpenTradeResult:
    approved: bool
    position: PaperPosition | None = None
    order: PaperOrder | None = None
    rejection_rule: str | None = None
    rejection_reason: str | None = None


async def _load_closed_trades(session: AsyncSession) -> list[ClosedTrade]:
    """The full realised-trade ledger, oldest first (needed for the §31
    consecutive-loss streak, which only means something in chronological
    order).
    """
    rows = (
        await session.execute(
            select(Trade).where(Trade.venue == VENUE).order_by(Trade.exit_time.asc())
        )
    ).scalars().all()
    return [
        ClosedTrade(
            symbol=row.symbol,
            quantity=Decimal(str(row.quantity)),
            entry_price=Decimal(str(row.entry_price)),
            exit_price=Decimal(str(row.exit_price)),
            entry_time=row.entry_time,
            exit_time=row.exit_time,
            gross_pnl=Decimal(str(row.gross_pnl)),
            fees=Decimal(str(row.fees)),
            slippage_cost=Decimal(str(row.slippage_cost)),
            net_pnl=Decimal(str(row.net_pnl)),
            return_pct=Decimal(str(row.return_pct)),
            exit_reason=row.exit_reason or "",
            mae=Decimal(str(row.mae)) if row.mae is not None else None,
            mfe=Decimal(str(row.mfe)) if row.mfe is not None else None,
            signal_id=row.signal_id,
        )
        for row in rows
    ]


async def _load_open_position_rows(session: AsyncSession) -> list[PaperPosition]:
    rows = (
        await session.execute(
            select(PaperPosition).where(PaperPosition.status == PositionStatus.OPEN.value)
        )
    ).scalars().all()
    return list(rows)


async def _peak_equity_from_snapshots(session: AsyncSession) -> Decimal:
    rows = (
        await session.execute(
            select(PortfolioSnapshot.equity).where(PortfolioSnapshot.venue == VENUE)
        )
    ).scalars().all()
    return max((Decimal(str(value)) for value in rows), default=Decimal(0))


def _last_exit_times(closed_trades: list[ClosedTrade]) -> dict[str, datetime]:
    last: dict[str, datetime] = {}
    for trade in closed_trades:
        current = last.get(trade.symbol)
        if current is None or trade.exit_time > current:
            last[trade.symbol] = trade.exit_time
    return last


async def load_portfolio(session: AsyncSession, settings: Settings) -> Portfolio:
    """Reconstruct the current paper account from persisted state.

    Deliberately derived from the ``trades``/``paper_positions`` ledgers
    rather than a separately stored balance field: a stored balance can
    drift from its own history, a derived one cannot (the ``xmax`` upsert
    trick and the health-aggregation logic elsewhere in this codebase make
    the same trade-off for the same reason).

    ``peak_equity`` is approximate: without a continuous mark-to-market loop
    (no scheduler exists yet), it can only be reconstructed from equity
    recorded at past actions (``portfolio_snapshots``), which under-counts
    any intrabar peak that occurred between two actions. This is a known,
    disclosed limitation (PROJECT_STATUS.md), not a silent one -- and it
    errs toward *under*-estimating the drawdown halt's headroom is a risk
    this system does not currently fully cover, not toward overstating safety.
    """
    initial_balance = Decimal(str(settings.paper_trading.initial_balance))
    closed_trades = await _load_closed_trades(session)
    open_rows = await _load_open_position_rows(session)

    positions: dict[str, OpenPosition] = {}
    open_cost_total = Decimal(0)
    for row in open_rows:
        entry_price = Decimal(str(row.entry_price))
        quantity = Decimal(str(row.quantity))
        fees_paid = Decimal(str(row.fees_paid))
        positions[row.symbol] = OpenPosition(
            symbol=row.symbol,
            quantity=quantity,
            entry_price=entry_price,
            entry_time=row.entry_time,
            stop_loss=Decimal(str(row.stop_loss)) if row.stop_loss is not None else None,
            take_profit=Decimal(str(row.take_profit)) if row.take_profit is not None else None,
            trailing_distance=Decimal(str(row.trailing_stop))
            if row.trailing_stop is not None
            else None,
            fees_paid=fees_paid,
            highest_price=entry_price,
            lowest_price=entry_price,
            signal_id=row.signal_id,
        )
        open_cost_total += quantity * entry_price + fees_paid

    realised_pnl = sum((trade.net_pnl for trade in closed_trades), Decimal(0))
    fees_from_closed = sum((trade.fees for trade in closed_trades), Decimal(0))
    total_fees = fees_from_closed + sum(
        (position.fees_paid for position in positions.values()), Decimal(0)
    )
    quote_balance = initial_balance + realised_pnl - open_cost_total

    snapshot_peak = await _peak_equity_from_snapshots(session)
    # Open positions valued at entry: no live mark is available here.
    current_equity_floor = quote_balance + open_cost_total
    peak_equity = max(initial_balance, current_equity_floor, snapshot_peak)

    return Portfolio(
        quote_balance=quote_balance,
        initial_balance=initial_balance,
        positions=positions,
        closed_trades=closed_trades,
        realised_pnl=realised_pnl,
        total_fees=total_fees,
        peak_equity=peak_equity,
    )


def _build_engine(portfolio: Portfolio, settings: Settings) -> PaperTradingEngine:
    engine = PaperTradingEngine(
        portfolio=portfolio,
        risk_engine=RiskEngine(settings.risk),
        config=SimulatorConfig(
            fee_rate=Decimal(str(settings.trading.taker_fee)),
            slippage_bps=Decimal(str(settings.paper_trading.slippage_bps)),
            allow_partial_fills=settings.paper_trading.allow_partial_fills,
        ),
    )
    engine._last_exit_time = _last_exit_times(portfolio.closed_trades)
    return engine


async def _reference_price(binance_service: BinanceService | None, symbol: str) -> Decimal:
    if binance_service is None:
        raise ServiceUnavailableError("Binance service is not initialised.")
    ticker = await binance_service.ticker(symbol)
    return ticker.price


async def _record_snapshot(
    session: AsyncSession, portfolio: Portfolio, prices: dict[str, Decimal]
) -> None:
    session.add(
        PortfolioSnapshot(
            venue=VENUE,
            timestamp=utc_now(),
            quote_balance=portfolio.quote_balance,
            positions_value=portfolio.positions_value(prices),
            equity=portfolio.equity(prices),
            realised_pnl=portfolio.realised_pnl,
            unrealised_pnl=portfolio.unrealised_pnl(prices),
            open_positions=len(portfolio.positions),
        )
    )


async def open_paper_trade(
    session: AsyncSession,
    settings: Settings,
    binance_service: BinanceService | None,
    *,
    symbol: str,
    stop_price: Decimal,
    take_profit: Decimal | None = None,
    trailing_distance: Decimal | None = None,
    signal_id: int | None = None,
) -> OpenTradeResult:
    portfolio = await load_portfolio(session, settings)
    if symbol in portfolio.positions:
        raise ValidationError(f"A paper position in {symbol} is already open.")

    reference_price = await _reference_price(binance_service, symbol)
    filters, _filters_source = resolve_symbol_filters(binance_service, symbol)
    engine = _build_engine(portfolio, settings)

    prices = {sym: pos.entry_price for sym, pos in portfolio.positions.items()}
    prices[symbol] = reference_price
    now = utc_now()

    assessment = engine.evaluate_entry(
        symbol=symbol,
        entry_price=reference_price,
        stop_price=stop_price,
        filters=filters,
        prices=prices,
        now=now,
        system=SystemState(),
        signal_id=signal_id,
    )
    if not assessment.approved:
        await record_risk_event(
            session, assessment, symbol=symbol, venue=VENUE, signal_id=signal_id
        )
        return OpenTradeResult(
            approved=False, rejection_rule=assessment.rule, rejection_reason=assessment.reason
        )

    position = engine.open_position(
        assessment=assessment,
        symbol=symbol,
        reference_price=reference_price,
        timestamp=now,
        filters=filters,
        stop_loss=stop_price,
        take_profit=take_profit,
        trailing_distance=trailing_distance,
        signal_id=signal_id,
    )
    if position is None:
        raise ValidationError("The fill produced zero quantity; nothing was opened.")

    order_row = PaperOrder(
        client_order_id=f"paper-{symbol}-{now.timestamp()}",
        signal_id=signal_id,
        symbol=symbol,
        side=OrderSide.BUY.value,
        order_type=OrderType.MARKET.value,
        status=OrderStatus.FILLED.value,
        quantity=position.quantity,
        price=reference_price,
        filled_quantity=position.quantity,
        average_fill_price=position.entry_price,
        fee=position.fees_paid,
        submitted_at=now,
        strategy_version=settings.models.strategy_version,
    )
    position_row = PaperPosition(
        symbol=symbol,
        status=PositionStatus.OPEN.value,
        quantity=position.quantity,
        entry_price=position.entry_price,
        entry_time=position.entry_time,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        trailing_stop=position.trailing_distance,
        fees_paid=position.fees_paid,
        signal_id=signal_id,
        strategy_version=settings.models.strategy_version,
    )
    session.add(order_row)
    session.add(position_row)
    await _record_snapshot(session, engine.portfolio, prices)
    await session.commit()

    logger.info(
        "Paper trade opened",
        extra={"event_type": "paper_trade_opened", "symbol": symbol, "signal_id": signal_id},
    )
    return OpenTradeResult(approved=True, position=position_row, order=order_row)


async def close_paper_trade(
    session: AsyncSession,
    settings: Settings,
    binance_service: BinanceService | None,
    *,
    symbol: str,
    reason: str = "MANUAL_EXIT",
    reference_price: Decimal | None = None,
) -> PaperPosition:
    """Close an open paper position.

    ``reference_price`` defaults to a fresh live ticker (the manual-close
    path). The scheduler's stop/target monitor passes the exact trigger
    price instead -- an exit fills at the stop/target price, not whatever
    the ticker happens to read a moment later, same principle as
    ``PaperTradingEngine.process_bar`` uses for a backtest.
    """
    open_row = (
        await session.execute(
            select(PaperPosition).where(
                PaperPosition.symbol == symbol, PaperPosition.status == PositionStatus.OPEN.value
            )
        )
    ).scalar_one_or_none()
    if open_row is None:
        raise ValidationError(f"No open paper position in {symbol}.")

    portfolio = await load_portfolio(session, settings)
    if reference_price is None:
        reference_price = await _reference_price(binance_service, symbol)
    filters, _filters_source = resolve_symbol_filters(binance_service, symbol)
    engine = _build_engine(portfolio, settings)
    now = utc_now()

    trade = engine.close_position(
        symbol=symbol,
        reference_price=reference_price,
        timestamp=now,
        reason=reason,
        filters=filters,
    )
    if trade is None:
        raise ValidationError(f"No open paper position in {symbol}.")

    order_row = PaperOrder(
        client_order_id=f"paper-{symbol}-exit-{now.timestamp()}",
        signal_id=open_row.signal_id,
        symbol=symbol,
        side=OrderSide.SELL.value,
        order_type=OrderType.MARKET.value,
        status=OrderStatus.FILLED.value,
        quantity=trade.quantity,
        price=reference_price,
        filled_quantity=trade.quantity,
        average_fill_price=trade.exit_price,
        fee=trade.fees - Decimal(str(open_row.fees_paid)),
        submitted_at=now,
        strategy_version=settings.models.strategy_version,
    )
    open_row.status = PositionStatus.CLOSED.value
    open_row.exit_price = trade.exit_price
    open_row.exit_time = trade.exit_time
    open_row.realised_pnl = trade.net_pnl
    open_row.fees_paid = trade.fees
    open_row.unrealised_pnl = None

    trade_row = Trade(
        venue=VENUE,
        symbol=symbol,
        position_id=open_row.id,
        signal_id=open_row.signal_id,
        side="BUY",
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        entry_time=trade.entry_time,
        exit_time=trade.exit_time,
        gross_pnl=trade.gross_pnl,
        fees=trade.fees,
        slippage_cost=trade.slippage_cost,
        net_pnl=trade.net_pnl,
        return_pct=trade.return_pct,
        mae=trade.mae,
        mfe=trade.mfe,
        exit_reason=trade.exit_reason,
        strategy_version=settings.models.strategy_version,
    )
    session.add(order_row)
    session.add(trade_row)
    await _record_snapshot(session, engine.portfolio, {symbol: reference_price})
    await session.commit()
    await session.refresh(open_row)

    logger.info(
        "Paper trade closed",
        extra={
            "event_type": "paper_trade_closed",
            "symbol": symbol,
            "net_pnl": str(trade.net_pnl),
            "reason": reason,
        },
    )
    return open_row


async def monitor_open_positions(
    session: AsyncSession, settings: Settings, binance_service: BinanceService | None
) -> int:
    """One scheduler tick (§16 Phase 16): check every open position's stop,
    target and trailing stop against a live price, and mark the account to
    market.

    A manually-placed paper trade previously only had its stop/target
    checked at the moment someone called ``close`` -- everything in between
    was invisible to the system. This is that continuous check,
    ``PaperTradingEngine.process_bar``'s per-candle logic adapted to a
    per-tick live price instead of a closed OHLC bar (``high=low=price``
    reduces ``exit_reason_for_bar`` to exactly the live-price comparison
    that needs, with no separate implementation).

    Returns the number of positions closed this tick. Never raises for a
    single symbol's price fetch failing -- one stale/unreachable symbol
    must not stop the rest of the book from being monitored (§44).
    """
    if binance_service is None:
        return 0

    open_rows = await _load_open_position_rows(session)
    if not open_rows:
        return 0

    prices: dict[str, Decimal] = {}
    closed_count = 0
    for row in open_rows:
        try:
            ticker = await binance_service.ticker(row.symbol)
        except Exception as exc:
            logger.warning(
                "Could not fetch a price to monitor an open position",
                extra={"event_type": "scheduler_price_unavailable", "symbol": row.symbol},
                exc_info=exc,
            )
            continue
        price = ticker.price
        prices[row.symbol] = price

        stop_loss = Decimal(str(row.stop_loss)) if row.stop_loss is not None else None
        take_profit = Decimal(str(row.take_profit)) if row.take_profit is not None else None
        reason = exit_reason_for_bar(
            high=price, low=price, stop_loss=stop_loss, take_profit=take_profit
        )
        if reason is not None:
            trigger_price = stop_loss if reason == "STOP_LOSS" else take_profit
            assert trigger_price is not None  # exit_reason_for_bar only fires when set
            try:
                await close_paper_trade(
                    session,
                    settings,
                    binance_service,
                    symbol=row.symbol,
                    reason=reason,
                    reference_price=trigger_price,
                )
                closed_count += 1
            except ValidationError:
                # Already closed by a concurrent action between the load and here.
                continue
            continue

        trailing_distance = (
            Decimal(str(row.trailing_stop)) if row.trailing_stop is not None else None
        )
        if trailing_distance is not None and trailing_distance > 0:
            new_stop = update_trailing_stop(
                current_stop=stop_loss, high=price, trailing_distance=trailing_distance
            )
            if new_stop is not None and (stop_loss is None or new_stop > stop_loss):
                row.stop_loss = new_stop
                session.add(row)

    await session.commit()

    if prices:
        portfolio = await load_portfolio(session, settings)
        await _record_snapshot(session, portfolio, prices)
        await session.commit()

    return closed_count
