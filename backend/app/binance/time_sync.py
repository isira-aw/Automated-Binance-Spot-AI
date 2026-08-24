"""Exchange time synchronisation (§72).

The laptop clock is never assumed accurate.  Every signed request is stamped
with server time reconstructed from a measured offset, and a ``-1021`` rejection
forces a re-sync rather than a wider ``recvWindow``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging_config import get_logger
from app.core.time_utils import utc_now

logger = get_logger("binance.time_sync")

# Drift beyond this is reported: it usually means the host clock is unmanaged,
# which will eventually break signed requests no matter how often we re-sync.
DRIFT_WARNING_MS = 1000


@dataclass
class TimeSync:
    """Tracks the offset between local and exchange time."""

    offset_ms: int = 0
    round_trip_ms: int = 0
    synced_at: str | None = None

    @property
    def synchronised(self) -> bool:
        return self.synced_at is not None

    def observe(self, *, sent_ms: int, server_ms: int, received_ms: int) -> None:
        """Record one server-time sample.

        The offset is measured against the midpoint of the request window
        rather than either endpoint, so that network latency contributes at
        most half the round trip to the estimate instead of all of it.
        """
        self.round_trip_ms = max(0, received_ms - sent_ms)
        midpoint = sent_ms + self.round_trip_ms // 2
        self.offset_ms = server_ms - midpoint
        self.synced_at = utc_now().isoformat()

        if abs(self.offset_ms) > DRIFT_WARNING_MS:
            logger.warning(
                "Local clock differs from exchange time",
                extra={
                    "event_type": "clock_drift",
                    "offset_ms": self.offset_ms,
                    "round_trip_ms": self.round_trip_ms,
                },
            )

    def timestamp_ms(self, *, now_ms: int | None = None) -> int:
        """Current exchange time in milliseconds, corrected by the offset."""
        local = now_ms if now_ms is not None else int(utc_now().timestamp() * 1000)
        return local + self.offset_ms

    def invalidate(self) -> None:
        """Drop the current estimate after a ``-1021`` rejection."""
        logger.warning(
            "Timestamp rejected by the exchange; re-synchronisation required",
            extra={"event_type": "clock_resync_required", "offset_ms": self.offset_ms},
        )
        self.synced_at = None
