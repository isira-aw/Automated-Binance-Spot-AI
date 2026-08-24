"""Configuration and environment-separation guarantees (§31, §64, §65, §99)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.config.risk_config import RiskConfig
from app.config.settings import TradingMode
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
