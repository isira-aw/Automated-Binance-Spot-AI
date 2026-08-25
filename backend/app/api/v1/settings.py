"""Settings endpoints — non-secret configuration for the frontend (§60, §98)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.deps import SettingsDep
from app.api.v1.system import INFLUENCING_SIGNALS, TIER1_COMPONENTS, TIER2_COMPONENTS
from app.schemas.system import (
    RiskConfigOut,
    SettingsOut,
    TierStatusOut,
    TradingSettingsOut,
)

router = APIRouter(prefix="/settings", tags=["settings"])


def _risk_out(risk: object) -> RiskConfigOut:
    """Coerce the Decimal-typed risk config into a JSON-friendly view."""
    return RiskConfigOut(
        **{
            key: (value if isinstance(value, int | bool) else float(value))
            for key, value in risk.model_dump().items()  # type: ignore[attr-defined]
        }
    )


@router.get("", response_model=SettingsOut, summary="Effective configuration")
async def read_settings(settings: SettingsDep) -> SettingsOut:
    """Effective configuration, with secrets reduced to presence flags.

    Binance keys are never returned — the frontend only learns whether
    credentials are configured (§10).
    """
    risk = settings.risk
    return SettingsOut(
        environment=settings.env.value,
        trading=TradingSettingsOut(
            assets=settings.trading.assets,
            timeframes=[tf.value for tf in settings.trading.timeframes],
            decision_timeframe=settings.trading.decision_timeframe.value,
            entry_timeframe=settings.trading.entry_timeframe.value,
            mode=settings.trading.mode.value,
            live_trading_enabled=settings.trading.live_trading_enabled,
            minimum_confidence=settings.trading.minimum_confidence,
            maker_fee=settings.trading.maker_fee,
            taker_fee=settings.trading.taker_fee,
        ),
        risk=_risk_out(risk),
        paper_trading=settings.paper_trading.model_dump(),
        backtesting=settings.backtesting.model_dump(),
        models=settings.models.model_dump(),
        binance={
            "testnet": settings.binance.testnet,
            "credentials_configured": settings.binance.has_credentials,
            "recv_window_ms": settings.binance.recv_window_ms,
        },
        tiers=TierStatusOut(
            tier1_components=TIER1_COMPONENTS,
            tier2_components=TIER2_COMPONENTS,
            tier2_enabled={
                "patterns": False,
                "market_regime": False,
                "transformer": settings.models.transformer_enabled,
                "ensemble": settings.models.ensemble_enabled,
                "news": settings.news.enabled,
                "fundamentals": settings.news.enabled,
                "ollama": settings.llm.ollama_enabled,
                "claude": settings.llm.claude_enabled,
            },
            influencing_signals=INFLUENCING_SIGNALS,
        ),
    )


@router.get("/risk", response_model=RiskConfigOut, summary="Authoritative risk limits")
async def read_risk(settings: SettingsDep) -> RiskConfigOut:
    """The single source of truth for risk parameters (§31)."""
    return _risk_out(settings.risk)
