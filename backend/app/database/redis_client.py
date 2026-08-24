"""Redis client for hot state and caching (§73).

PostgreSQL remains the persistent source of truth; anything stored here must be
reconstructible after a Redis flush.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.config import Settings

_client: Redis | None = None


def init_redis(settings: Settings) -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.redis.url, encoding="utf-8", decode_responses=True
        )
    return _client


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis client is not initialised; call init_redis().")
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def check_redis(client: Redis) -> bool:
    return bool(await client.ping())
