"""Client-side rate limiting driven by the exchange's own declared limits (§71).

No limit value is hard-coded.  Limits are read from ``exchangeInfo`` at
runtime; the configured fallbacks apply only until that first response arrives,
and are deliberately conservative.

The limiter is a weighted sliding window per interval, matching how Binance
accounts for request weight.  Exceeding a limit is treated as a bug in this
client, not as something to discover by being banned.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field

from app.core.logging_config import get_logger
from app.core.time_utils import utc_now

logger = get_logger("binance.rate_limiter")

# Binance expresses windows as (intervalNum, interval-letter).
_INTERVAL_SECONDS = {"SECOND": 1, "MINUTE": 60, "HOUR": 3600, "DAY": 86400}


@dataclass(frozen=True)
class RateLimitRule:
    """One limit as declared by ``exchangeInfo``."""

    limit_type: str  # REQUEST_WEIGHT | ORDERS | RAW_REQUESTS
    interval_seconds: int
    limit: int

    @classmethod
    def from_exchange_info(cls, entry: dict[str, object]) -> RateLimitRule | None:
        """Build a rule from one ``rateLimits`` entry, or ``None`` if unusable.

        Unknown interval names are skipped rather than guessed — an unenforced
        limit is safer than one enforced against an invented window.
        """
        try:
            interval = str(entry["interval"]).upper()
            interval_num = int(entry["intervalNum"])  # type: ignore[call-overload]
            limit = int(entry["limit"])  # type: ignore[call-overload]
            limit_type = str(entry["rateLimitType"]).upper()
        except (KeyError, TypeError, ValueError):
            logger.warning(
                "Skipping unparsable rate limit entry",
                extra={"event_type": "rate_limit_unparsable"},
            )
            return None

        seconds = _INTERVAL_SECONDS.get(interval)
        if seconds is None or interval_num <= 0 or limit <= 0:
            logger.warning(
                "Skipping rate limit with an unrecognised interval",
                extra={"event_type": "rate_limit_unknown_interval", "interval": interval},
            )
            return None
        return cls(
            limit_type=limit_type,
            interval_seconds=seconds * interval_num,
            limit=limit,
        )


@dataclass
class _Window:
    """Sliding window of (timestamp, weight) for a single rule."""

    rule: RateLimitRule
    entries: deque[tuple[float, int]] = field(default_factory=deque)
    used: int = 0

    def _evict(self, now: float) -> None:
        cutoff = now - self.rule.interval_seconds
        while self.entries and self.entries[0][0] <= cutoff:
            _, weight = self.entries.popleft()
            self.used -= weight

    def wait_seconds(self, now: float, weight: int) -> float:
        """Seconds to wait before ``weight`` fits, or 0.0 if it fits now."""
        self._evict(now)
        if self.used + weight <= self.rule.limit:
            return 0.0
        # Wait until enough of the oldest entries age out.
        needed = self.used + weight - self.rule.limit
        freed = 0
        for timestamp, entry_weight in self.entries:
            freed += entry_weight
            if freed >= needed:
                return max(0.0, timestamp + self.rule.interval_seconds - now)
        # A single request heavier than the whole limit can never fit.
        return float("inf")

    def record(self, now: float, weight: int) -> None:
        self.entries.append((now, weight))
        self.used += weight


class RateLimiter:
    """Enforces every declared limit before a request leaves the process."""

    def __init__(self, rules: list[RateLimitRule] | None = None) -> None:
        self._windows: dict[tuple[str, int], _Window] = {}
        self._lock = asyncio.Lock()
        self._from_exchange = False
        if rules:
            self._install(rules)

    def _install(self, rules: list[RateLimitRule]) -> None:
        self._windows = {
            (rule.limit_type, rule.interval_seconds): _Window(rule) for rule in rules
        }

    @property
    def configured_from_exchange(self) -> bool:
        """True once live ``exchangeInfo`` limits replaced the fallbacks."""
        return self._from_exchange

    @property
    def rules(self) -> list[RateLimitRule]:
        return [window.rule for window in self._windows.values()]

    def update_from_exchange_info(self, payload: dict[str, object]) -> None:
        """Replace the active rules with those declared by the exchange."""
        raw = payload.get("rateLimits")
        if not isinstance(raw, list):
            logger.warning(
                "exchangeInfo carried no rateLimits; keeping current rules",
                extra={"event_type": "rate_limit_missing"},
            )
            return
        rules = [
            rule
            for rule in (
                RateLimitRule.from_exchange_info(entry)
                for entry in raw
                if isinstance(entry, dict)
            )
            if rule is not None
        ]
        if not rules:
            logger.warning(
                "No usable rate limits in exchangeInfo; keeping current rules",
                extra={"event_type": "rate_limit_unusable"},
            )
            return
        self._install(rules)
        self._from_exchange = True
        logger.info(
            "Rate limits loaded from exchangeInfo",
            extra={"event_type": "rate_limit_loaded", "rule_count": len(rules)},
        )

    async def acquire(self, *, weight: int = 1, limit_type: str = "REQUEST_WEIGHT") -> None:
        """Block until ``weight`` fits within every applicable window.

        ``RAW_REQUESTS`` windows count each call as 1 regardless of weight,
        which is how Binance accounts for them.
        """
        while True:
            async with self._lock:
                now = utc_now().timestamp()
                delay = 0.0
                for (rule_type, _), window in self._windows.items():
                    cost = 1 if rule_type == "RAW_REQUESTS" else weight
                    if rule_type not in {limit_type, "RAW_REQUESTS"}:
                        continue
                    wait = window.wait_seconds(now, cost)
                    if wait == float("inf"):
                        raise ValueError(
                            f"A request of weight {weight} can never satisfy "
                            f"{rule_type} limit of {window.rule.limit}."
                        )
                    delay = max(delay, wait)

                if delay <= 0.0:
                    for (rule_type, _), window in self._windows.items():
                        if rule_type not in {limit_type, "RAW_REQUESTS"}:
                            continue
                        window.record(now, 1 if rule_type == "RAW_REQUESTS" else weight)
                    return

            logger.debug(
                "Throttling request to stay inside declared limits",
                extra={"event_type": "rate_limit_throttled", "delay_seconds": delay},
            )
            await asyncio.sleep(delay)
