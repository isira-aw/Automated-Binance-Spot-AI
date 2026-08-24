"""Configuration and environment-separation guarantees (§31, §64, §65, §99)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config.risk_config import RiskConfig
from app.config.settings import Settings, TradingMode
from tests.conftest import make_settings


def test_risk_config_is_immutable():
    """Risk limits are the single source of truth and cannot be mutated ad hoc."""
    risk = RiskConfig()
    with pytest.raises(ValidationError):
        risk.max_daily_loss = Decimal("0.99")  # type: ignore[misc]


def test_risk_config_rejects_out_of_range_limits():
    with pytest.raises(ValidationError):
        RiskConfig(max_risk_per_trade=Decimal("1.5"))
    with pytest.raises(ValidationError):
        RiskConfig(max_simultaneous_positions=0)


def test_risk_config_rejects_unknown_parameters():
    """Prevents a risk parameter being silently redefined under a new name."""
    with pytest.raises(ValidationError):
        RiskConfig(max_leverage=Decimal("2"))  # type: ignore[call-arg]


def test_live_trading_is_disabled_by_default():
    settings = make_settings(env="development")
    assert settings.trading.live_trading_enabled is False
    assert settings.trading.mode is not TradingMode.LIVE


def test_live_mode_without_the_enable_flag_is_a_blocking_error():
    settings = make_settings(env="paper", trading={"mode": "LIVE", "live_trading_enabled": False})
    problems = settings.validate_environment()
    assert any("LIVE" in problem for problem in problems)


def test_wildcard_cors_is_rejected_in_production():
    settings = make_settings(env="production", cors_allow_origins=["*"])
    assert any("CORS" in problem for problem in settings.validate_environment())


def test_wildcard_cors_is_tolerated_outside_production():
    settings = make_settings(env="development", cors_allow_origins=["*"])
    assert settings.validate_environment() == []


def test_cors_origins_parse_from_a_comma_separated_string():
    settings = make_settings(cors_allow_origins="http://a.local, http://b.local")
    assert settings.cors_allow_origins == ["http://a.local", "http://b.local"]


def test_docs_are_disabled_in_production():
    assert make_settings(env="production").docs_enabled is False
    assert make_settings(env="development").docs_enabled is True


def test_tier2_components_default_to_disabled():
    """Tier 1 must run with the whole intelligence layer switched off (§1a, §6)."""
    settings = make_settings()
    assert settings.llm.claude_enabled is False
    assert settings.llm.ollama_enabled is False
    assert settings.news.enabled is False
    assert settings.models.transformer_enabled is False
    assert settings.models.ensemble_enabled is False
    assert settings.models.lightgbm_enabled is True


def test_database_url_never_leaks_into_the_repository_defaults():
    settings = make_settings()
    assert settings.database.async_url.startswith("postgresql+asyncpg://")
    assert settings.database.sync_url.startswith("postgresql+psycopg://")


class TestEnvListParsing:
    """List settings are supplied as flat env vars (§64).

    pydantic-settings JSON-decodes list fields from the environment before any
    validator runs, so a comma-separated value raises SettingsError unless the
    field opts out with NoDecode.  These fields are populated straight from
    .env, so the failure surfaces only under a real environment -- which is
    exactly how it reached a container once already.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (
                "http://localhost:5173,http://localhost:3000",
                ["http://localhost:5173", "http://localhost:3000"],
            ),
            ('["http://x","http://y"]', ["http://x", "http://y"]),
            ("http://solo", ["http://solo"]),
            (" http://a , http://b ", ["http://a", "http://b"]),
        ],
    )
    def test_cors_origins_accepts_csv_and_json(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
    ) -> None:
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", raw)
        assert Settings(_env_file=None).cors_allow_origins == expected

    def test_assets_accept_csv_and_are_uppercased(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ASSETS", "btcusdt, ethusdt")
        assert Settings(_env_file=None).trading.assets == ["BTCUSDT", "ETHUSDT"]

    def test_timeframes_accept_csv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TIMEFRAMES", "4h,15m")
        settings = Settings(_env_file=None)
        assert [tf.value for tf in settings.trading.timeframes] == ["4h", "15m"]

    def test_defaults_apply_when_unset(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.cors_allow_origins == ["http://localhost:5173"]
        assert settings.trading.assets == ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


class TestFlatEnvVarsReachNestedSections:
    """Nested sections must read the flat variables documented in .env.example.

    A plain BaseModel nested in BaseSettings never consults the environment, so
    these were silently ignored in favour of defaults.
    """

    def test_postgres_credentials_are_honoured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POSTGRES_PASSWORD", "secret123")
        monkeypatch.setenv("POSTGRES_HOST", "pg-host")
        database = Settings(_env_file=None).database
        assert database.password == "secret123"
        assert database.host == "pg-host"

    def test_special_characters_survive_url_building(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:w0rd/50%x")
        url = make_url(Settings(_env_file=None).database.sync_url)
        assert url.password == "p@ss:w0rd/50%x"
        assert url.host == "postgres"

    def test_safety_toggles_are_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BINANCE_TESTNET", "false")
        monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
        settings = Settings(_env_file=None)
        assert settings.binance.testnet is False
        assert settings.trading.live_trading_enabled is True
