"""The unattended heartbeat (§16 Phase 16).

Every Tier 1 decision-making piece existed before this module but nothing
ran any of it unattended: candle-close feature computation is event-driven
off the live WebSocket stream (Phase 5/8, still true, not rebuilt here), but
a manually-placed paper position's stop/target/trailing stop was only ever
checked at the moment someone called ``close`` (Phase 15b). This is the loop
that closes that gap -- a small, explicit ``asyncio`` task, not a new
scheduling framework, since one periodic job is what exists to run.

A tick failing must never stop the loop (§44): the same "degrade, don't
crash" principle the market-data stream bridge uses.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from app.config import Settings
from app.core.logging_config import get_logger
from app.core.time_utils import utc_now
from app.database.session import session_scope
from app.models.enums import ComponentHealth
from app.monitoring.health import ComponentStatus
from app.paper_trading.account import monitor_open_positions

if TYPE_CHECKING:
    from app.binance.service import BinanceService

logger = get_logger("scheduler.service")


class SchedulerService:
    """Runs :func:`monitor_open_positions` on a fixed interval."""

    def __init__(
        self, settings: Settings, get_binance_service: Callable[[], BinanceService | None]
    ) -> None:
        self._settings = settings
        self._get_binance_service = get_binance_service
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self.tick_count = 0
        self.positions_closed_total = 0
        self.last_tick_at: datetime | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if not self._settings.scheduler.enabled:
            logger.info("Scheduler disabled by configuration; not starting.")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="scheduler-loop")
        logger.info(
            "Scheduler started",
            extra={
                "event_type": "scheduler_started",
                "interval_seconds": self._settings.scheduler.interval_seconds,
            },
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Scheduler stopped", extra={"event_type": "scheduler_stopped"})

    async def _loop(self) -> None:
        interval = self._settings.scheduler.interval_seconds
        while self._running:
            await self._tick()
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        try:
            async with session_scope() as session:
                closed = await monitor_open_positions(
                    session, self._settings, self._get_binance_service()
                )
            self.positions_closed_total += closed
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)
            logger.error(
                "Scheduler tick failed", extra={"event_type": "scheduler_tick_failed"}, exc_info=exc
            )
        finally:
            self.tick_count += 1
            self.last_tick_at = utc_now()

    async def probe(self) -> ComponentStatus:
        if not self._settings.scheduler.enabled:
            return ComponentStatus(
                name="scheduler",
                status=ComponentHealth.DISABLED,
                detail="Disabled by configuration.",
            )
        if not self._running:
            return ComponentStatus(
                name="scheduler", status=ComponentHealth.OFFLINE, detail="Scheduler is not running."
            )
        metadata = {
            "tick_count": self.tick_count,
            "positions_closed_total": self.positions_closed_total,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
        }
        if self.last_error:
            return ComponentStatus(
                name="scheduler",
                status=ComponentHealth.DEGRADED,
                detail=f"Last tick failed: {self.last_error}",
                metadata=metadata,
            )
        return ComponentStatus(name="scheduler", status=ComponentHealth.ONLINE, metadata=metadata)
