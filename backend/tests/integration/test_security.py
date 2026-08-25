"""Security invariants that must never regress (§60, §70, §99, §108).

These are the properties whose violation would be catastrophic and silent:
a withdrawal capability appearing, a secret reaching a client, or an error
handing an attacker the internals. Each is asserted against the real
application, not by reading the code.
"""

from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from tests.conftest import make_settings

BACKEND = Path(__file__).resolve().parents[2]


class TestNoWithdrawalCapability:
    """§70: the platform must be structurally incapable of moving funds off
    the exchange -- not merely disinclined to."""

    def test_no_withdrawal_endpoint_is_routed(self, client: TestClient):
        for path in ("/api/v1/withdraw", "/api/v1/binance/withdraw", "/api/v1/transfer"):
            assert client.post(path).status_code in (404, 405, 501)

    def test_the_binance_package_contains_no_withdrawal_call(self):
        """A withdrawal needs the exchange's withdraw endpoint; if that
        string never appears, the capability cannot exist by accident."""
        offenders = []
        for source in (BACKEND / "app").rglob("*.py"):
            text = source.read_text(encoding="utf-8").lower()
            if "sapi/v1/capital/withdraw" in text or "/wapi/" in text:
                offenders.append(str(source.relative_to(BACKEND)))
        assert offenders == []

    def test_no_transfer_or_margin_endpoints_are_referenced(self):
        """Spot only (§9): no futures, no margin, no internal transfers."""
        forbidden = ("/fapi/", "/dapi/", "sapi/v1/margin", "sapi/v1/asset/transfer")
        offenders = []
        for source in (BACKEND / "app").rglob("*.py"):
            text = source.read_text(encoding="utf-8").lower()
            for needle in forbidden:
                if needle in text:
                    offenders.append(f"{source.relative_to(BACKEND)}: {needle}")
        assert offenders == []


class TestSecretsNeverReachAClient:
    def test_the_settings_endpoint_reports_presence_not_values(self, client: TestClient):
        body = client.get("/api/v1/settings").json()
        serialised = json.dumps(body)

        assert "api_key" not in serialised
        assert "api_secret" not in serialised
        # Presence flag only.
        assert "credentials_configured" in serialised

    def test_no_settings_response_field_looks_like_a_credential(self, client: TestClient):
        serialised = json.dumps(client.get("/api/v1/settings").json()).lower()
        for needle in ("secret", "password", "private_key", "token"):
            assert needle not in serialised, f"{needle!r} appears in the settings response"

    def test_the_env_example_carries_placeholders_only(self):
        """§60: a real key must never be committed. The example file is the
        one most likely to catch a careless paste."""
        example = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
        for line in example.splitlines():
            if line.startswith("BINANCE_API_KEY=") or line.startswith("BINANCE_API_SECRET="):
                value = line.split("=", 1)[1].strip()
                # Binance keys are 64 chars; a placeholder must not look like one.
                assert len(value) < 32, f"{line.split('=')[0]} looks like a real key"


class TestErrorsDoNotLeakInternals:
    def test_an_unknown_route_returns_the_envelope_without_internals(
        self, client: TestClient
    ):
        body = client.get("/api/v1/definitely-not-a-route").json()
        assert set(body) == {"error"}
        serialised = json.dumps(body).lower()
        assert "traceback" not in serialised
        assert "/home/" not in serialised
        assert "sqlalchemy" not in serialised

    def test_a_validation_error_uses_the_envelope(self, client: TestClient):
        """`/models/train` takes no database dependency, so a malformed body
        is rejected by validation rather than failing on a missing session."""
        response = client.post("/api/v1/models/train", json={})
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        # The envelope shape holds even on the validation path.
        assert set(body) == {"error"}


class TestSecurityHeaders:
    def test_responses_carry_the_baseline_headers(self, client: TestClient):
        headers = client.get("/api/v1/system/ping").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"

    def test_error_responses_carry_them_too(self, client: TestClient):
        """An error path is exactly where a forgotten header matters."""
        headers = client.get("/api/v1/definitely-not-a-route").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"

    def test_hsts_is_not_sent(self, client: TestClient):
        """Deliberate: this is a local-first platform on plain HTTP, and an
        HSTS header would poison the browser's cache for localhost."""
        assert "strict-transport-security" not in client.get("/api/v1/system/ping").headers


class TestProductionConfiguration:
    def test_wildcard_cors_is_rejected_in_production(self):
        settings = make_settings(env="production", cors_allow_origins=["*"])
        problems = settings.validate_environment()
        assert any("CORS" in problem for problem in problems)

    def test_api_docs_are_disabled_in_production(self):
        """§108: Swagger is a development affordance; it maps the whole
        attack surface for anyone who reaches the port."""
        assert make_settings(env="production").docs_enabled is False
        assert make_settings(env="development").docs_enabled is True

    def test_live_trading_requires_an_explicit_second_switch(self):
        """§106: a mode change alone must never arm real money."""
        settings = make_settings(env="development", trading={"mode": "LIVE"})
        problems = settings.validate_environment()
        assert problems, "TRADING_MODE=LIVE without LIVE_TRADING_ENABLED must be refused"

    def test_live_trading_is_off_by_default(self):
        settings = make_settings()
        assert settings.trading.live_trading_enabled is False
        assert settings.trading.mode.value == "PAPER"
