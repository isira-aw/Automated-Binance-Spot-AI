"""Historical data integrity validation (§17).

Checks stored candles for duplicates, gaps, timestamp misalignment, OHLC
inconsistency and abnormal values, and records the result in
``market_data_metadata`` rather than only logging it -- so integrity state
survives a restart and is queryable by the frontend Data page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import floor_to_timeframe, timeframe_seconds, utc_now
from app.models.market import Candle, MarketDataMetadata

# A move larger than this between consecutive closes is flagged for review,
# not rejected -- crypto genuinely gaps this much during real events, so this
# is a signal for a human to look at, never an automatic data deletion.
ABNORMAL_MOVE_FRACTION = 0.5


@dataclass
class IntegrityReport:
    symbol: str
    timeframe: str
    candle_count: int = 0
    expected_count: int | None = None
    missing_candles: int = 0
    duplicate_open_times: int = 0
    misaligned_timestamps: list[str] = field(default_factory=list)
    ohlc_violations: list[str] = field(default_factory=list)
    non_positive_values: list[str] = field(default_factory=list)
    abnormal_moves: list[str] = field(default_factory=list)
    checked_at: str = ""

    @property
    def is_clean(self) -> bool:
        return not (
            self.duplicate_open_times
            or self.misaligned_timestamps
            or self.ohlc_violations
            or self.non_positive_values
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_count": self.candle_count,
            "expected_count": self.expected_count,
            "missing_candles": self.missing_candles,
            "duplicate_open_times": self.duplicate_open_times,
            "misaligned_timestamps": self.misaligned_timestamps[:20],
            "ohlc_violations": self.ohlc_violations[:20],
            "non_positive_values": self.non_positive_values[:20],
            "abnormal_moves": self.abnormal_moves[:20],
            "is_clean": self.is_clean,
            "checked_at": self.checked_at,
        }


async def validate_symbol_timeframe(
    session: AsyncSession, *, symbol: str, timeframe: str, source: str = "BINANCE"
) -> IntegrityReport:
    report = IntegrityReport(symbol=symbol, timeframe=timeframe)

    rows = (
        (
            await session.execute(
                select(Candle)
                .where(
                    Candle.symbol == symbol,
                    Candle.timeframe == timeframe,
                    Candle.source == source,
                    Candle.is_closed.is_(True),
                )
                .order_by(Candle.open_time)
            )
        )
        .scalars()
        .all()
    )
    report.candle_count = len(rows)
    report.checked_at = utc_now().isoformat()

    if not rows:
        return report

    step_seconds = timeframe_seconds(timeframe)
    seen_open_times: set[datetime] = set()
    previous: Candle | None = None

    for row in rows:
        if row.open_time in seen_open_times:
            report.duplicate_open_times += 1
        seen_open_times.add(row.open_time)

        if floor_to_timeframe(row.open_time, timeframe) != row.open_time:
            report.misaligned_timestamps.append(row.open_time.isoformat())

        values = (row.open, row.high, row.low, row.close, row.volume)
        if any(v is not None and float(v) <= 0 for v in values[:4]) or (
            row.volume is not None and float(row.volume) < 0
        ):
            report.non_positive_values.append(row.open_time.isoformat())
        elif float(row.high) < max(float(row.open), float(row.close), float(row.low)) or float(
            row.low
        ) > min(float(row.open), float(row.close), float(row.high)):
            report.ohlc_violations.append(row.open_time.isoformat())

        if previous is not None:
            gap = (row.open_time - previous.open_time).total_seconds()
            if gap > step_seconds:
                report.missing_candles += int(gap / step_seconds) - 1
            prev_close = float(previous.close)
            if prev_close > 0:
                move = abs(float(row.close) - prev_close) / prev_close
                if move > ABNORMAL_MOVE_FRACTION:
                    report.abnormal_moves.append(row.open_time.isoformat())
        previous = row

    span_seconds = (rows[-1].open_time - rows[0].open_time).total_seconds()
    report.expected_count = int(span_seconds / step_seconds) + 1

    await _persist_report(session, report, source=source)
    return report


async def _persist_report(
    session: AsyncSession, report: IntegrityReport, *, source: str
) -> None:
    result = await session.execute(
        select(MarketDataMetadata).where(
            MarketDataMetadata.symbol == report.symbol,
            MarketDataMetadata.timeframe == report.timeframe,
            MarketDataMetadata.source == source,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = MarketDataMetadata(symbol=report.symbol, timeframe=report.timeframe, source=source)
        session.add(row)

    row.candle_count = report.candle_count
    row.missing_candles = report.missing_candles
    row.last_integrity_check = utc_now()
    row.integrity_report = report.to_dict()
    await session.commit()


async def validate_all_configured(
    session: AsyncSession, *, symbols: list[str], timeframes: list[str], source: str = "BINANCE"
) -> list[IntegrityReport]:
    """Validate every configured symbol/timeframe pair.

    Pairs with zero stored candles are skipped rather than reported as
    failing -- nothing has been ingested for them yet, which is a different
    condition from ingested-but-corrupt data.
    """
    reports = []
    for symbol in symbols:
        for timeframe in timeframes:
            count = await session.scalar(
                select(func.count()).select_from(Candle).where(
                    Candle.symbol == symbol,
                    Candle.timeframe == timeframe,
                    Candle.source == source,
                )
            )
            if not count:
                continue
            reports.append(
                await validate_symbol_timeframe(
                    session, symbol=symbol, timeframe=timeframe, source=source
                )
            )
    return reports
