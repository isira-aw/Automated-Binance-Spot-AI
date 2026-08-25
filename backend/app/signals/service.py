"""Orchestrates fusion: load components, fuse, persist the decision chain (§30b, §79).

Every attempt persists a :class:`Signal` row with its :class:`SignalComponent`
children -- whether or not it results in a trade (§54: WAIT and
NO_VALID_SETUP are first-class outcomes, not failures to record). The natural
key (``symbol``, ``timeframe``, ``open_time``, ``strategy_version``, venue) is
upserted, so re-running fusion for a bar that was already evaluated updates
the same row rather than duplicating it -- reproducibility (§80) means the
same inputs always produce the same recorded signal, not a growing history of
identical re-evaluations.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.logging_config import get_logger
from app.ml.prediction import predict_latest
from app.ml.training import model_id_for
from app.models.enums import ModelStatus, SignalComponentKind
from app.models.market import TechnicalFeature
from app.models.ml import ModelVersion
from app.models.trading import Signal, SignalComponent
from app.signals.fusion import ComponentScore, fuse
from app.signals.technical_score import TECHNICAL_SCORE_VERSION, compute_technical_score

logger = get_logger("signals.service")

VENUE = "PAPER"


async def _latest_technical_feature(
    session: AsyncSession, *, symbol: str, timeframe: str, feature_version: str
) -> TechnicalFeature | None:
    return (
        await session.execute(
            select(TechnicalFeature)
            .where(
                TechnicalFeature.symbol == symbol,
                TechnicalFeature.timeframe == timeframe,
                TechnicalFeature.feature_version == feature_version,
            )
            .order_by(TechnicalFeature.open_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _best_lightgbm_version(
    session: AsyncSession, *, symbol: str, timeframe: str
) -> ModelVersion | None:
    """The best available registry entry for this symbol/timeframe.

    Prefers VALIDATED over CANDIDATE, and the most recently created within
    that preference -- there is no PRODUCTION concept reachable yet (Phase 12
    backtesting exists, but nothing has promoted a model through it), so this
    is deliberately not a search for a PRODUCTION row that cannot exist.
    """
    rows = (
        await session.execute(
            select(ModelVersion)
            .where(
                ModelVersion.model_id == model_id_for(symbol, timeframe),
                ModelVersion.status.in_(
                    [ModelStatus.VALIDATED.value, ModelStatus.CANDIDATE.value]
                ),
            )
            .order_by(ModelVersion.created_at.desc())
        )
    ).scalars().all()
    if not rows:
        return None
    validated = [r for r in rows if r.status == ModelStatus.VALIDATED.value]
    return validated[0] if validated else rows[0]


def _lightgbm_fusion_score(prediction) -> float:
    """The class-probability mapping §30a documents by name for LightGBM."""
    from app.ml.prediction import fusion_score_from_probabilities

    return fusion_score_from_probabilities(float(prediction.prob_up), float(prediction.prob_down))


async def _technical_component(
    session: AsyncSession, *, symbol: str, timeframe: str, feature_version: str, weight: float
) -> tuple[ComponentScore, TechnicalFeature | None]:
    feature_row = await _latest_technical_feature(
        session, symbol=symbol, timeframe=timeframe, feature_version=feature_version
    )
    if feature_row is None:
        return (
            ComponentScore(
                kind=SignalComponentKind.TECHNICAL, score=0.5, weight=weight, confidence=0.0,
                version=TECHNICAL_SCORE_VERSION, active=False,
                details={"reason": "No technical features computed yet."},
            ),
            None,
        )
    score, confidence, details = compute_technical_score(feature_row.features)
    return (
        ComponentScore(
            kind=SignalComponentKind.TECHNICAL, score=score, weight=weight, confidence=confidence,
            version=TECHNICAL_SCORE_VERSION, active=True, details=details,
        ),
        feature_row,
    )


async def _lightgbm_component(
    session: AsyncSession, *, symbol: str, timeframe: str, weight: float, models_root: Path
) -> ComponentScore:
    model = await _best_lightgbm_version(session, symbol=symbol, timeframe=timeframe)
    if model is None:
        return ComponentScore(
            kind=SignalComponentKind.LIGHTGBM, score=0.5, weight=weight, confidence=0.0,
            version="none", active=False, details={"reason": "No registered LightGBM model."},
        )

    prediction = await predict_latest(
        session, model_id=model.model_id, version=model.version, models_root=models_root
    )
    if prediction is None:
        return ComponentScore(
            kind=SignalComponentKind.LIGHTGBM, score=0.5, weight=weight, confidence=0.0,
            version=model.version, active=False,
            details={"reason": "Model registered but no prediction could be produced."},
        )
    return ComponentScore(
        kind=SignalComponentKind.LIGHTGBM,
        score=_lightgbm_fusion_score(prediction),
        weight=weight,
        confidence=float(prediction.confidence),
        version=model.version,
        active=True,
        details={
            "prob_up": float(prediction.prob_up),
            "prob_neutral": float(prediction.prob_neutral),
            "prob_down": float(prediction.prob_down),
        },
    )


async def generate_signal(
    session: AsyncSession, settings: Settings, *, symbol: str, timeframe: str
) -> Signal | None:
    """Fuse the Tier 1 components for the latest closed bar and persist the result.

    Returns ``None`` only when there is no technical feature row at all to
    anchor a signal to -- with nothing to reference an ``open_time`` from,
    there is nothing meaningful to record (as distinct from NO_VALID_SETUP,
    which *is* recorded: components were evaluated and none had an opinion).
    """
    technical, feature_row = await _technical_component(
        session,
        symbol=symbol,
        timeframe=timeframe,
        feature_version=settings.models.feature_version,
        weight=settings.models.technical_component_weight,
    )
    if feature_row is None:
        return None

    lightgbm = await _lightgbm_component(
        session,
        symbol=symbol,
        timeframe=timeframe,
        weight=settings.models.lightgbm_component_weight,
        models_root=settings.paths.root,
    )

    result = fuse(
        [technical, lightgbm],
        min_confidence=settings.models.fusion_min_confidence,
        action_margin=settings.models.fusion_action_margin,
    )

    signal = await _persist(
        session,
        symbol=symbol,
        timeframe=timeframe,
        open_time=feature_row.open_time,
        strategy_version=settings.models.strategy_version,
        result=result,
    )
    logger.info(
        "Signal generated",
        extra={
            "event_type": "signal_generated",
            "symbol": symbol,
            "timeframe": timeframe,
            "action": result.action.value,
        },
    )
    return signal


async def _persist(
    session: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    open_time,
    strategy_version: str,
    result,
) -> Signal:
    stmt = (
        pg_insert(Signal)
        .values(
            symbol=symbol,
            timeframe=timeframe,
            open_time=open_time,
            generated_at=_now(),
            action=result.action.value,
            score=result.score,
            confidence=result.confidence,
            reason_codes=result.reason_codes,
            strategy_version=strategy_version,
            fusion_method="weighted_average_v1",
            venue=VENUE,
        )
        .on_conflict_do_update(
            constraint="uq_signals_symbol",
            set_={
                "generated_at": _now(),
                "action": result.action.value,
                "score": result.score,
                "confidence": result.confidence,
                "reason_codes": result.reason_codes,
            },
        )
        .returning(Signal.id)
    )
    signal_id = (await session.execute(stmt)).scalar_one()

    await session.execute(
        SignalComponent.__table__.delete().where(SignalComponent.signal_id == signal_id)
    )
    for component in result.components:
        await session.execute(
            pg_insert(SignalComponent).values(
                signal_id=signal_id,
                kind=component.kind.value,
                score=component.score,
                weight=component.weight,
                confidence=component.confidence,
                version=component.version,
                active=component.active,
                details=component.details or None,
            )
        )
    await session.commit()

    return (await session.execute(select(Signal).where(Signal.id == signal_id))).scalar_one()


def _now():
    from app.core.time_utils import utc_now

    return utc_now()
