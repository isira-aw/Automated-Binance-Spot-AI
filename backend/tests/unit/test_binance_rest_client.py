"""REST client error classification, retries and signing (§9, §44, §71, §72)."""

from __future__ import annotations

import httpx
import pytest

from app.binance.errors import (
    BinanceAuthError,
    BinanceRateLimitError,
    BinanceRequestError,
    BinanceServerError,
    BinanceTransportError,
)
from app.binance.rest_client import (
    MAINNET_BASE_URL,
    TESTNET_BASE_URL,
    BinanceRestClient,
)
from tests.conftest import make_settings


def build_client(
    responses: list[object], *, settings=None
) -> tuple[BinanceRestClient, list[httpx.Request]]:
    """Client backed by a scripted transport.  Never touches the network."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0) if queue else queue_last
        if isinstance(item, Exception):
            raise item
        return item

    queue_last = httpx.Response(200, json={})
    settings = settings or make_settings()
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://example.invalid")
    return BinanceRestClient(settings, client=http), seen


def test_testnet_flag_selects_the_base_url():
    """Live endpoints must never be reached while testnet is configured."""
    testnet = BinanceRestClient(make_settings(binance={"testnet": True}))
    live = BinanceRestClient(make_settings(binance={"testnet": False}))
    assert testnet.base_url == TESTNET_BASE_URL
    assert live.base_url == MAINNET_BASE_URL


@pytest.mark.asyncio
async def test_successful_response_resets_the_failure_counter():
    client, _ = build_client([httpx.Response(200, json={"ok": True})])
    client.consecutive_failures = 3
    assert await client.get("/api/v3/ping") == {"ok": True}
    assert client.consecutive_failures == 0
    await client.aclose()


@pytest.mark.asyncio
async def test_client_errors_are_not_retried():
    """A 400 will be rejected identically however many times it is sent."""
    client, seen = build_client([httpx.Response(400, json={"code": -1100, "msg": "bad"})])
    with pytest.raises(BinanceRequestError):
        await client.get("/api/v3/klines")
    assert len(seen) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_server_errors_are_retried_then_surface():
    settings = make_settings(binance={"max_retries": 2, "retry_backoff_seconds": 0.0})
    client, seen = build_client([httpx.Response(503) for _ in range(5)], settings=settings)
    with pytest.raises(BinanceServerError):
        await client.get("/api/v3/ping")
    assert len(seen) == 3  # initial attempt plus two retries
    await client.aclose()


@pytest.mark.asyncio
async def test_transport_failure_is_retried_and_classified():
    settings = make_settings(binance={"max_retries": 1, "retry_backoff_seconds": 0.0})
    client, seen = build_client(
        [httpx.ConnectError("no route"), httpx.ConnectError("no route")], settings=settings
    )
    with pytest.raises(BinanceTransportError):
        await client.get("/api/v3/ping")
    assert len(seen) == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_recovery_after_a_retry_returns_the_payload():
    settings = make_settings(binance={"max_retries": 2, "retry_backoff_seconds": 0.0})
    client, _ = build_client(
        [httpx.Response(503), httpx.Response(200, json={"recovered": True})],
        settings=settings,
    )
    assert await client.get("/api/v3/ping") == {"recovered": True}
    await client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_is_classified_and_honours_retry_after():
    settings = make_settings(binance={"max_retries": 0, "retry_backoff_seconds": 0.0})
    client, _ = build_client(
        [
            httpx.Response(
                429,
                headers={"Retry-After": "7"},
                json={"code": -1003, "msg": "too many"},
            )
        ],
        settings=settings,
    )
    with pytest.raises(BinanceRateLimitError) as excinfo:
        await client.get("/api/v3/ping")
    assert excinfo.value.retry_after_seconds == 7.0
    assert excinfo.value.retryable is True
    await client.aclose()


@pytest.mark.asyncio
async def test_backoff_never_undercuts_retry_after():
    """Ignoring Retry-After escalates to an IP ban (§71)."""
    client, _ = build_client([])
    error = BinanceRateLimitError("slow down", retry_after_seconds=30.0)
    assert client._backoff_seconds(1, error) >= 30.0
    await client.aclose()


@pytest.mark.asyncio
async def test_ip_ban_status_is_treated_as_rate_limiting():
    settings = make_settings(binance={"max_retries": 0})
    client, _ = build_client([httpx.Response(418, json={"msg": "banned"})], settings=settings)
    with pytest.raises(BinanceRateLimitError):
        await client.get("/api/v3/ping")
    await client.aclose()


@pytest.mark.asyncio
async def test_timestamp_rejection_triggers_a_resync():
    """-1021 must re-sync the clock, never widen recvWindow (§72)."""
    settings = make_settings(binance={"max_retries": 1, "retry_backoff_seconds": 0.0})
    client, _ = build_client(
        [
            httpx.Response(400, json={"code": -1021, "msg": "outside recvWindow"}),
            httpx.Response(200, json={"serverTime": 1_700_000_000_000}),
            httpx.Response(200, json={"ok": True}),
        ],
        settings=settings,
    )
    assert await client.get("/api/v3/ping") == {"ok": True}
    assert client.time_sync.synchronised is True
    assert client._settings.binance.recv_window_ms == make_settings().binance.recv_window_ms
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_failure_is_not_retried():
    client, seen = build_client([httpx.Response(401, json={"code": -2015, "msg": "invalid key"})])
    with pytest.raises(BinanceAuthError):
        await client.get("/api/v3/account", signed=False)
    assert len(seen) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_error_messages_never_carry_the_signature():
    """Error text is surfaced to logs and the UI; it must not leak secrets."""
    settings = make_settings(
        binance={"api_key": "public-key", "api_secret": "super-secret", "max_retries": 0}
    )
    client, _ = build_client(
        [httpx.Response(401, json={"code": -1022, "msg": "bad sig"})], settings=settings
    )
    with pytest.raises(BinanceAuthError) as excinfo:
        await client.get("/api/v3/account", signed=True)
    rendered = f"{excinfo.value.message}{excinfo.value.metadata}"
    assert "super-secret" not in rendered
    assert "signature" not in rendered.lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_signing_requires_credentials():
    client, seen = build_client(
        [], settings=make_settings(binance={"api_key": "", "api_secret": ""})
    )
    with pytest.raises(BinanceAuthError, match="without credentials"):
        await client.get("/api/v3/account", signed=True)
    assert seen == []
    await client.aclose()


@pytest.mark.asyncio
async def test_signed_request_sends_key_header_and_signature():
    settings = make_settings(binance={"api_key": "public-key", "api_secret": "super-secret"})
    client, seen = build_client([httpx.Response(200, json={})], settings=settings)
    await client.get("/api/v3/account", params={"a": "1"}, signed=True)
    request = seen[0]
    assert request.headers["X-MBX-APIKEY"] == "public-key"
    assert "signature=" in str(request.url)
    assert "recvWindow=" in str(request.url)
    await client.aclose()


@pytest.mark.asyncio
async def test_signature_matches_the_query_that_is_sent():
    """Re-encoding params after signing would invalidate the signature."""
    import hashlib
    import hmac

    settings = make_settings(binance={"api_key": "k", "api_secret": "s"})
    client, seen = build_client([httpx.Response(200, json={})], settings=settings)
    await client.get("/api/v3/account", params={"symbol": "BTCUSDT"}, signed=True)

    sent = dict(httpx.QueryParams(seen[0].url.query.decode()))
    signature = sent.pop("signature")
    from urllib.parse import urlencode

    expected = hmac.new(b"s", urlencode(sent).encode(), hashlib.sha256).hexdigest()
    assert signature == expected
    await client.aclose()
