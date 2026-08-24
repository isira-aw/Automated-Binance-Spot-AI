"""Market data API surface (§59): backfill trigger and status.

Endpoints that only read persisted data (coverage, candles, integrity) need a
live database and are exercised in test_historical_ingestion.py instead; this
file covers the parts reachable without one.
"""

from __future__ import annotations

import pytest

from app.core.errors import ServiceUnavailableError
from app.services.historical_ingestion import get_ingestion_tracker


@pytest.fixture(autouse=True)
def _reset_tracker():
    get_ingestion_tracker().current = None
    yield
    get_ingestion_tracker().current = None


def test_backfill_without_a_connected_exchange_returns_service_unavailable(client):
    """No app.state.binance in the test app -- must fail clearly, not 500."""
    response = client.post("/api/v1/market/backfill")
    assert response.status_code == ServiceUnavailableError.status_code
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_backfill_status_with_no_job_returns_null(client):
    response = client.get("/api/v1/market/backfill/status")
    assert response.status_code == 200
    assert response.json() is None


def test_backfill_rejects_a_concurrent_start(client, app):
    """A second trigger while one job is running must not silently queue or
    clobber the first -- it is rejected with a clear reason."""
    from unittest.mock import AsyncMock

    binance = AsyncMock()
    app.state.binance = binance

    get_ingestion_tracker().start()  # simulate an in-flight job

    response = client.post("/api/v1/market/backfill")
    assert response.status_code == 422
    assert "already running" in response.json()["error"]["message"]


def test_backfill_accepts_a_new_job(client, app):
    from unittest.mock import AsyncMock

    app.state.binance = AsyncMock()

    response = client.post("/api/v1/market/backfill")
    assert response.status_code == 202
    body = response.json()
    assert body["running"] is True
    assert body["results"] == []


def test_a_whole_job_failure_is_surfaced_not_swallowed(client, app):
    """No database in this test app, so the background task fails before any
    symbol/timeframe runs.  That must show up as job.error, not disappear."""
    from unittest.mock import AsyncMock

    app.state.binance = AsyncMock()

    client.post("/api/v1/market/backfill")

    import time

    deadline = time.monotonic() + 2
    status = None
    while time.monotonic() < deadline:
        status = client.get("/api/v1/market/backfill/status").json()
        if status["running"] is False:
            break
        time.sleep(0.02)

    assert status is not None
    assert status["running"] is False
    assert status["error"] is not None
    assert status["results"] == []
