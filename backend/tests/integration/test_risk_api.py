"""Risk API surface (§31, §59)."""

from __future__ import annotations


def test_parameters_expose_every_documented_risk_limit(client):
    """§31 defines the limits once; the API must expose that same set, so a
    parameter added to RiskConfig cannot silently go unsurfaced."""
    from app.config.risk_config import RiskConfig

    response = client.get("/api/v1/risk/parameters")
    assert response.status_code == 200
    assert set(response.json()) == set(RiskConfig().model_dump())


def test_parameters_are_read_only(client):
    """Changing a limit is a Settings concern, not the risk namespace's."""
    for method in (client.post, client.put, client.patch, client.delete):
        response = method("/api/v1/risk/parameters")
        assert response.status_code in (404, 405)


def test_events_and_state_routes_are_registered_not_pending(client):
    """These need a live database, so they are exercised for real in the DB
    integration suite. Here we only assert the routes exist and are no longer
    served by the NOT_IMPLEMENTED placeholder router."""
    paths = {route.path for route in client.app.routes}
    assert "/api/v1/risk/events" in paths
    assert "/api/v1/risk/state" in paths

    from app.api.v1.not_implemented import PENDING_NAMESPACES

    assert "risk" not in PENDING_NAMESPACES
