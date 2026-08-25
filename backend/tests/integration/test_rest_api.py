"""REST contract: health, settings, error envelope, CORS, NOT IMPLEMENTED."""

from __future__ import annotations

from starlette.testclient import TestClient


def test_health_reports_every_component(client: TestClient):
    response = client.get("/api/v1/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "ONLINE"
    assert set(body["components"]) >= {"backend", "database", "redis"}


def test_unbuilt_components_report_not_implemented_not_healthy(client: TestClient):
    """§96: an unbuilt engine is never dressed up as a working one."""
    components = client.get("/api/v1/system/health").json()["components"]
    assert components["binance"]["status"] == "NOT_IMPLEMENTED"
    assert components["claude"]["status"] == "DISABLED"


def test_ping_is_a_cheap_liveness_probe(client: TestClient):
    assert client.get("/api/v1/system/ping").json() == {"status": "online"}


def test_settings_never_expose_binance_credentials(client: TestClient):
    """§10, §60: secrets never reach the frontend."""
    body = client.get("/api/v1/settings").json()
    serialised = response_text = str(body)
    assert "api_key" not in serialised
    assert "api_secret" not in response_text
    assert body["binance"]["credentials_configured"] is False
    assert body["binance"]["testnet"] is True


def test_settings_expose_the_authoritative_risk_limits(client: TestClient):
    """§31: the frontend reads risk parameters from one place."""
    risk = client.get("/api/v1/settings/risk").json()
    expected = {
        "max_risk_per_trade",
        "max_daily_loss",
        "max_portfolio_exposure",
        "max_asset_exposure",
        "max_position_size",
        "max_simultaneous_positions",
        "max_drawdown",
        "max_consecutive_losses",
        "max_slippage",
        "spread_protection",
        "volatility_protection",
        "stale_data_protection_seconds",
        "api_failure_protection_threshold",
        "model_health_protection",
        "cooldown_period_seconds",
    }
    assert set(risk) == expected
    assert client.get("/api/v1/settings").json()["risk"] == risk


def test_live_trading_is_off_and_unarmed_in_the_default_configuration(client: TestClient):
    trading = client.get("/api/v1/settings").json()["trading"]
    assert trading["live_trading_enabled"] is False
    assert trading["mode"] == "PAPER"


def test_tier_status_reports_nothing_influencing_signals_yet(client: TestClient):
    """§14: the UI must be able to tell shadow/research from live influence."""
    tiers = client.get("/api/v1/system/tiers").json()
    assert tiers["influencing_signals"] == []
    assert "lightgbm" in tiers["tier1_components"]
    assert "claude" in tiers["tier2_components"]
    assert all(enabled is False for enabled in tiers["tier2_enabled"].values())


def test_unbuilt_namespaces_return_the_not_implemented_envelope(client: TestClient):
    response = client.get("/api/v1/orders")
    assert response.status_code == 501
    error = response.json()["error"]
    assert error["code"] == "NOT_IMPLEMENTED"
    assert error["metadata"]["namespace"] == "orders"


def test_every_documented_namespace_exists_in_the_api(client: TestClient):
    """§59: the namespace list is stable even before the engines land."""
    from app.api.v1.not_implemented import PENDING_NAMESPACES

    for namespace in PENDING_NAMESPACES:
        assert client.get(f"/api/v1/{namespace}").status_code == 501


def test_unknown_route_uses_the_documented_error_envelope(client: TestClient):
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found", "metadata": None}
    }


def test_every_response_carries_a_request_id(client: TestClient):
    response = client.get("/api/v1/system/ping")
    assert response.headers["x-request-id"]


def test_supplied_request_id_is_echoed_back(client: TestClient):
    response = client.get("/api/v1/system/ping", headers={"x-request-id": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"


def test_cors_allows_the_configured_origin_only(client: TestClient):
    allowed = client.get(
        "/api/v1/system/ping", headers={"Origin": "http://localhost:5173"}
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"

    denied = client.get("/api/v1/system/ping", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in denied.headers


def test_openapi_documents_the_api(client: TestClient):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/system/health" in schema["paths"]
    assert "/api/v1/settings" in schema["paths"]
