"""Historical data ingestion (§17, §18, §67 phase 6).

Backfills the maximum available history per symbol/timeframe independently —
BTC, ETH and BNB need not share a start date — and persists it resumably.  A
run interrupted partway through resumes from the last persisted candle rather
than restarting, which is exercised directly by a test (§ "partial-restore
recovery" spirit extended to ingestion).

Only closed candles are ever persisted (§16, §18): the in-progress bar the
exchange returns at the end of a page is dropped, never stored as if it were
final.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.binance.market_data import Kline, MarketDataService
from app.core.logging_config import get_logger
from app.core.time_utils import timeframe_seconds, to_utc, utc_now
from app.models.market import Candle, MarketDataMetadata

logger = get_logger("services.historical_ingestion")

KLINES_PER_PAGE = 1000

# Predates every Binance Spot symbol.  Used only when no prior candle exists
# for a symbol/timeframe; Binance returns data starting at the symbol's actual
# listing time regardless, so this does not need to be precise per asset (§17).
EARLIEST_POSSIBLE_MS = 1_262_304_000_000  # 2010-01-01T00:00:00Z

# Bounds a single ingestion call so one request can never run unbounded (§53).
DEFAULT_MAX_PAGES = 200


@dataclass
class IngestionResult:
    """Outcome of backfilling one symbol/timeframe."""

    symbol: str
    timeframe: str
    pages_fetched: int = 0
    candles_inserted: int = 0
    candles_updated: int = 0
    reached_present: bool = False
    stopped_reason: str = "not_started"
    error: str | None = None


async def _resume_point(
    session: AsyncSession, *, symbol: str, timeframe: str, source: str
) -> int | None:
    """Millisecond timestamp to resume from, or ``None`` to start from scratch."""
    result = await session.execute(
        select(MarketDataMetadata.last_candle_open).where(
            MarketDataMetadata.symbol == symbol,
            MarketDataMetadata.timeframe == timeframe,
            MarketDataMetadata.source == source,
        )
    )
    last_open = result.scalar_one_or_none()
    if last_open is None:
        return None
    step_ms = timeframe_seconds(timeframe) * 1000
    return int(to_utc(last_open).timestamp() * 1000) + step_ms


async def _upsert_candles(
    session: AsyncSession, klines: list[Kline], *, source: str
) -> tuple[int, int]:
    """Insert closed candles, updating any that already exist (e.g. a
    previously-open candle that has since closed).  Returns (inserted, updated).
    """
    if not klines:
        return 0, 0

    rows = [
        {
            "symbol": kline.symbol,
            "timeframe": kline.timeframe,
            "open_time": kline.open_time,
            "close_time": kline.close_time,
            "open": kline.open,
            "high": kline.high,
            "low": kline.low,
            "close": kline.close,
            "volume": kline.volume,
            "quote_volume": kline.quote_volume,
            "trades": kline.trades,
            "is_closed": True,
            "source": source,
        }
        for kline in klines
    ]

    stmt = pg_insert(Candle).values(rows)
    upsert_columns = (
        "close_time", "open", "high", "low", "close", "volume", "quote_volume", "trades",
    )
    update_cols = {col: getattr(stmt.excluded, col) for col in upsert_columns}
    stmt = stmt.on_conflict_do_update(
        constraint="uq_candles_symbol",
        set_=update_cols,
    ).returning(Candle.id, literal_column("(xmax = 0)").label("was_insert"))

    result = await session.execute(stmt)
    outcomes = result.all()
    # Postgres sets xmax = 0 on a freshly inserted row and non-zero on a row
    # that ON CONFLICT touched via UPDATE -- the standard idiom for telling
    # the two apart from a single upsert statement.
    inserted = sum(1 for _, was_insert in outcomes if was_insert)
    return inserted, len(outcomes) - inserted


async def _update_metadata(
    session: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    source: str,
    first_open: datetime | None,
    last_open: datetime | None,
    inserted: int,
) -> None:
    result = await session.execute(
        select(MarketDataMetadata).where(
            MarketDataMetadata.symbol == symbol,
            MarketDataMetadata.timeframe == timeframe,
            MarketDataMetadata.source == source,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = MarketDataMetadata(symbol=symbol, timeframe=timeframe, source=source)
        session.add(row)

    if first_open is not None and (
        row.first_candle_open is None or first_open < row.first_candle_open
    ):
        row.first_candle_open = first_open
    if last_open is not None and (
        row.last_candle_open is None or last_open > row.last_candle_open
    ):
        row.last_candle_open = last_open
    row.candle_count = (row.candle_count or 0) + inserted


async def persist_closed_candle(
    session: AsyncSession, kline: Kline, *, source: str = "BINANCE"
) -> None:
    """Persist a single live closed candle and commit.

    Used by the market stream bridge so every closed bar the exchange reports
    lands in Postgres the same way a backfilled one does -- the technical
    engine has only one candle source to trust, not "backfilled history plus
    whatever the stream happened to keep in memory" (§16, §18).
    """
    if not kline.is_closed:
        raise ValueError("persist_closed_candle received an open candle.")

    inserted, updated = await _upsert_candles(session, [kline], source=source)
    await _update_metadata(
        session,
        symbol=kline.symbol,
        timeframe=kline.timeframe,
        source=source,
        first_open=kline.open_time,
        last_open=kline.open_time,
        inserted=inserted,
    )
    await session.commit()


async def backfill_symbol_timeframe(
    session: AsyncSession,
    market_data: MarketDataService,
    *,
    symbol: str,
    timeframe: str,
    source: str = "BINANCE",
    max_pages: int = DEFAULT_MAX_PAGES,
) -> IngestionResult:
    """Backfill one symbol/timeframe from where it last left off.

    Commits after every page so an interruption loses at most one page of
    progress rather than the whole run.
    """
    result = IngestionResult(symbol=symbol, timeframe=timeframe, stopped_reason="in_progress")
    start_ms = await _resume_point(session, symbol=symbol, timeframe=timeframe, source=source)
    if start_ms is None:
        start_ms = EARLIEST_POSSIBLE_MS

    step_ms = timeframe_seconds(timeframe) * 1000

    for _ in range(max_pages):
        klines = await market_data.klines(
            symbol, timeframe, limit=KLINES_PER_PAGE, start_ms=start_ms
        )
        result.pages_fetched += 1

        closed = [k for k in klines if k.is_closed]
        if closed:
            inserted, updated = await _upsert_candles(session, closed, source=source)
            result.candles_inserted += inserted
            result.candles_updated += updated
            await _update_metadata(
                session,
                symbol=symbol,
                timeframe=timeframe,
                source=source,
                first_open=closed[0].open_time,
                last_open=closed[-1].open_time,
                inserted=inserted,
            )
            await session.commit()
            start_ms = int(closed[-1].open_time.timestamp() * 1000) + step_ms

        # Fewer closed candles than a full page means the stream has caught
        # up to the present -- there is nothing older left to backfill.
        if len(closed) < KLINES_PER_PAGE:
            result.reached_present = True
            result.stopped_reason = "reached_present"
            return result

    result.stopped_reason = "max_pages_reached"
    return result


@dataclass
class IngestionJob:
    """Tracks one backfill run across multiple symbol/timeframe pairs."""

    started_at: str
    finished_at: str | None = None
    running: bool = False
    results: list[IngestionResult] = field(default_factory=list)
    # A failure of the whole job (e.g. the database was unreachable before any
    # symbol/timeframe could even start), distinct from a per-pair error in
    # `results` -- without this, a total failure would finish silently with an
    # empty result list and no indication anything went wrong.
    error: str | None = None

    @property
    def total_candles(self) -> int:
        return sum(r.candles_inserted for r in self.results)

    def to_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "running": self.running,
            "error": self.error,
            "total_candles_inserted": self.total_candles,
            "results": [
                {
                    "symbol": r.symbol,
                    "timeframe": r.timeframe,
                    "pages_fetched": r.pages_fetched,
                    "candles_inserted": r.candles_inserted,
                    "candles_updated": r.candles_updated,
                    "reached_present": r.reached_present,
                    "stopped_reason": r.stopped_reason,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class IngestionJobTracker:
    """In-memory record of the most recent backfill job.

    A restart loses this in-memory status, but never loses ingested data: every
    committed candle and its metadata are already durable in PostgreSQL, and
    the next run resumes from there (§89, §90).
    """

    def __init__(self) -> None:
        self.current: IngestionJob | None = None
        # Holds a strong reference to the running asyncio.Task so it cannot
        # be garbage-collected mid-run; set/cleared by the API layer.
        self.background_task: object | None = None

    def start(self) -> IngestionJob:
        job = IngestionJob(started_at=utc_now().isoformat(), running=True)
        self.current = job
        return job

    def finish(self, job: IngestionJob) -> None:
        job.running = False
        job.finished_at = utc_now().isoformat()


_tracker = IngestionJobTracker()


def get_ingestion_tracker() -> IngestionJobTracker:
    return _tracker
