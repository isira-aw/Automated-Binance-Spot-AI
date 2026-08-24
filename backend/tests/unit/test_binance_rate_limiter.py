"""Rate limiting must come from the exchange's declared limits, never from
remembered constants (§71)."""

from __future__ import annotations

import asyncio

import pytest

from app.binance.rate_limiter import RateLimiter, RateLimitRule


def test_rule_parses_exchange_info_entry():
    rule = RateLimitRule.from_exchange_info(
        {
            "rateLimitType": "REQUEST_WEIGHT",
            "interval": "MINUTE",
            "intervalNum": 1,
            "limit": 6000,
        }
    )
    assert rule == RateLimitRule("REQUEST_WEIGHT", 60, 6000)


def test_rule_multiplies_interval_num():
    rule = RateLimitRule.from_exchange_info(
        {
            "rateLimitType": "ORDERS",
            "interval": "SECOND",
            "intervalNum": 10,
            "limit": 100,
        }
    )
    assert rule is not None
    assert rule.interval_seconds == 10


@pytest.mark.parametrize(
    "entry",
    [
        {"rateLimitType": "X", "interval": "FORTNIGHT", "intervalNum": 1, "limit": 5},
        {"rateLimitType": "X", "interval": "MINUTE", "intervalNum": 0, "limit": 5},
        {"rateLimitType": "X", "interval": "MINUTE", "intervalNum": 1, "limit": 0},
        {"interval": "MINUTE"},
    ],
)
def test_unusable_entries_are_skipped_not_guessed(entry):
    """An unenforced limit is safer than one enforced against an invented window."""
    assert RateLimitRule.from_exchange_info(entry) is None


def test_limits_are_replaced_by_exchange_info():
    limiter = RateLimiter([RateLimitRule("REQUEST_WEIGHT", 60, 100)])
    assert limiter.configured_from_exchange is False

    limiter.update_from_exchange_info(
        {
            "rateLimits": [
                {
                    "rateLimitType": "REQUEST_WEIGHT",
                    "interval": "MINUTE",
                    "intervalNum": 1,
                    "limit": 6000,
                }
            ]
        }
    )
    assert limiter.configured_from_exchange is True
    assert limiter.rules == [RateLimitRule("REQUEST_WEIGHT", 60, 6000)]


def test_malformed_payload_keeps_existing_rules():
    """A bad response must not silently remove all throttling."""
    original = [RateLimitRule("REQUEST_WEIGHT", 60, 100)]
    limiter = RateLimiter(original)
    limiter.update_from_exchange_info({"rateLimits": "not-a-list"})
    assert limiter.rules == original
    limiter.update_from_exchange_info({"rateLimits": []})
    assert limiter.rules == original


@pytest.mark.asyncio
async def test_requests_within_limit_do_not_block():
    limiter = RateLimiter([RateLimitRule("REQUEST_WEIGHT", 60, 10)])
    await asyncio.wait_for(
        asyncio.gather(*(limiter.acquire(weight=1) for _ in range(10))), timeout=1
    )


@pytest.mark.asyncio
async def test_exceeding_the_limit_blocks():
    """The eleventh unit of weight cannot be issued inside the window."""
    limiter = RateLimiter([RateLimitRule("REQUEST_WEIGHT", 60, 10)])
    for _ in range(10):
        await limiter.acquire(weight=1)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.acquire(weight=1), timeout=0.25)


@pytest.mark.asyncio
async def test_window_frees_up_as_entries_age_out():
    limiter = RateLimiter([RateLimitRule("REQUEST_WEIGHT", 1, 2)])
    await limiter.acquire(weight=2)
    await asyncio.wait_for(limiter.acquire(weight=2), timeout=3)


@pytest.mark.asyncio
async def test_raw_requests_count_calls_not_weight():
    """RAW_REQUESTS counts one per call however heavy the request is."""
    limiter = RateLimiter([RateLimitRule("RAW_REQUESTS", 60, 3)])
    for _ in range(3):
        await limiter.acquire(weight=50)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(limiter.acquire(weight=1), timeout=0.25)


@pytest.mark.asyncio
async def test_order_limit_does_not_throttle_market_data():
    """A saturated ORDERS window must not block read-only requests."""
    limiter = RateLimiter(
        [
            RateLimitRule("ORDERS", 10, 1),
            RateLimitRule("REQUEST_WEIGHT", 60, 100),
        ]
    )
    await limiter.acquire(weight=1, limit_type="ORDERS")
    await asyncio.wait_for(limiter.acquire(weight=1), timeout=0.5)


@pytest.mark.asyncio
async def test_impossible_weight_raises_rather_than_hanging():
    limiter = RateLimiter([RateLimitRule("REQUEST_WEIGHT", 60, 5)])
    with pytest.raises(ValueError, match="never satisfy"):
        await limiter.acquire(weight=10)
