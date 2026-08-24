"""Binance Spot REST client (§9, §71, §72).

Spot endpoints only.  No futures, no margin, and no withdrawal endpoint exists
anywhere in this class (§70) — the surface simply is not implemented, so it
cannot be reached by accident or by a mistaken caller.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from app.binance.errors import (
    CODE_INVALID_SIGNATURE,
    CODE_INVALID_TIMESTAMP,
    BinanceAuthError,
    BinanceError,
    BinanceRateLimitError,
    BinanceRequestError,
    BinanceServerError,
    BinanceTimestampError,
    BinanceTransportError,
)
from app.binance.rate_limiter import RateLimiter
from app.binance.time_sync import TimeSync
from app.config import Settings
from app.core.logging_config import get_logger
from app.core.time_utils import utc_now

logger = get_logger("binance.rest")

MAINNET_BASE_URL = "https://api.binance.com"
TESTNET_BASE_URL = "https://testnet.binance.vision"

Method = Literal["GET", "POST", "DELETE"]


class BinanceRestClient:
    """Async REST client with rate limiting, retries and signed requests."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
        time_sync: TimeSync | None = None,
    ) -> None:
        self._settings = settings
        self._binance = settings.binance
        self.base_url = TESTNET_BASE_URL if self._binance.testnet else MAINNET_BASE_URL
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._binance.rest_timeout_seconds,
            headers={"User-Agent": "automated-binance-spot-ai/1.0"},
        )
        self.rate_limiter = rate_limiter or RateLimiter(_fallback_rules(settings))
        self.time_sync = time_sync or TimeSync()
        self.consecutive_failures = 0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- public surface ---------------------------------------------------

    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        weight: int = 1,
        signed: bool = False,
    ) -> Any:
        return await self._request("GET", path, params=params, weight=weight, signed=signed)

    async def server_time_ms(self) -> int:
        """Fetch server time and update the offset estimate."""
        sent = int(utc_now().timestamp() * 1000)
        payload = await self.get("/api/v3/time", weight=1)
        received = int(utc_now().timestamp() * 1000)
        server_ms = int(payload["serverTime"])
        self.time_sync.observe(sent_ms=sent, server_ms=server_ms, received_ms=received)
        return server_ms

    async def ping(self) -> bool:
        await self.get("/api/v3/ping", weight=1)
        return True

    # -- request pipeline -------------------------------------------------

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Attach timestamp, recvWindow and HMAC signature.

        The signature is computed over the exact encoded query that is sent;
        re-encoding it afterwards would invalidate it.
        """
        if not self._binance.has_credentials:
            raise BinanceAuthError(
                "A signed Binance request was attempted without credentials."
            )
        params = dict(params)
        params["timestamp"] = self.time_sync.timestamp_ms()
        params["recvWindow"] = self._binance.recv_window_ms
        query = urlencode(params, doseq=True)
        signature = hmac.new(
            self._binance.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    async def _request(
        self,
        method: Method,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        weight: int = 1,
        signed: bool = False,
    ) -> Any:
        attempt = 0
        last_error: BinanceError | None = None

        while attempt <= self._binance.max_retries:
            attempt += 1
            await self.rate_limiter.acquire(weight=weight)

            request_params = dict(params or {})
            headers: dict[str, str] = {}
            if signed:
                request_params = self._sign(request_params)
                headers["X-MBX-APIKEY"] = self._binance.api_key

            try:
                response = await self._client.request(
                    method, path, params=request_params, headers=headers
                )
            except httpx.HTTPError as exc:
                last_error = BinanceTransportError(f"Binance request failed: {exc}")
            else:
                try:
                    return self._handle_response(response, path=path)
                except BinanceError as exc:
                    last_error = exc
                    if isinstance(exc, BinanceTimestampError):
                        # Re-sync once, then retry with a corrected timestamp
                        # rather than widening recvWindow (§72).
                        self.time_sync.invalidate()
                        with contextlib.suppress(BinanceError):
                            # A failed re-sync is not fatal here: the retry
                            # below will surface the original rejection.
                            await self.server_time_ms()
                    if not exc.retryable:
                        self.consecutive_failures += 1
                        raise

            assert last_error is not None
            if attempt > self._binance.max_retries:
                break

            delay = self._backoff_seconds(attempt, last_error)
            logger.warning(
                "Retrying Binance request",
                extra={
                    "event_type": "binance_retry",
                    "path": path,
                    "attempt": attempt,
                    "delay_seconds": delay,
                    "reason": last_error.code,
                },
            )
            await asyncio.sleep(delay)

        self.consecutive_failures += 1
        assert last_error is not None
        raise last_error

    def _backoff_seconds(self, attempt: int, error: BinanceError) -> float:
        """Exponential backoff, but never shorter than a served ``Retry-After``."""
        base = self._binance.retry_backoff_seconds * (2 ** (attempt - 1))
        if isinstance(error, BinanceRateLimitError) and error.retry_after_seconds:
            return max(base, error.retry_after_seconds)
        return base

    def _handle_response(self, response: httpx.Response, *, path: str) -> Any:
        status = response.status_code

        if status == 200:
            self.consecutive_failures = 0
            return response.json()

        binance_code, message = _extract_error(response)

        if status in (429, 418):
            retry_after = response.headers.get("Retry-After")
            raise BinanceRateLimitError(
                f"Binance rate limit hit on {path}: {message}",
                binance_code=binance_code,
                http_status=status,
                retry_after_seconds=float(retry_after) if retry_after else None,
            )
        if status >= 500:
            raise BinanceServerError(
                f"Binance server error on {path}: {message}",
                binance_code=binance_code,
                http_status=status,
            )
        if binance_code == CODE_INVALID_TIMESTAMP:
            raise BinanceTimestampError(
                f"Request timestamp outside recvWindow on {path}: {message}",
                binance_code=binance_code,
                http_status=status,
            )
        if status in (401, 403) or binance_code == CODE_INVALID_SIGNATURE:
            # Deliberately does not echo params: they carry the signature.
            raise BinanceAuthError(
                f"Binance rejected the credentials for {path}.",
                binance_code=binance_code,
                http_status=status,
            )
        raise BinanceRequestError(
            f"Binance rejected the request to {path}: {message}",
            binance_code=binance_code,
            http_status=status,
        )


def _extract_error(response: httpx.Response) -> tuple[int | None, str]:
    try:
        body = response.json()
    except ValueError:
        return None, response.text[:200]
    if isinstance(body, dict):
        code = body.get("code")
        return (int(code) if isinstance(code, int) else None), str(body.get("msg", ""))
    return None, str(body)[:200]


def _fallback_rules(settings: Settings) -> list[Any]:
    """Conservative limits used only until live ``exchangeInfo`` arrives (§71)."""
    from app.binance.rate_limiter import RateLimitRule

    return [
        RateLimitRule(
            limit_type="REQUEST_WEIGHT",
            interval_seconds=60,
            limit=settings.binance.fallback_request_weight_per_minute,
        ),
        RateLimitRule(
            limit_type="ORDERS",
            interval_seconds=1,
            limit=settings.binance.fallback_orders_per_second,
        ),
    ]
