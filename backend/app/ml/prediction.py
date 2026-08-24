"""Runs inference with a registered model and persists the result (§26, §30a).

Implements the unified [0,1] fusion score mapping §30a specifies by name for
LightGBM: ``P(up) - P(down)`` rescaled to ``[0, 1]``.  This is the one central,
versioned mapping every future signal-fusion component adapter must reuse —
it is not reinvented per component.

Every prediction stored right now is ``shadow_mode=True`` unconditionally: no
risk engine (Phase 10), paper trading simulator (Phase 11) or signal fusion
(Phase 13) exists yet to act on one, so nothing currently produced by this
module can influence a trade even in principle (§96 — this is a statement of
present fact, not a policy toggle to remember to flip later; the day a real
consumer exists, this module's shadow_mode default is exactly what changes).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.core.time_utils import utc_now
from app.ml.dataset import encode_features
from app.ml.lightgbm_model import load, predict_proba, predicted_class_probabilities
from app.models.market import TechnicalFeature
from app.models.ml import ModelPrediction, ModelVersion


def fusion_score_from_probabilities(prob_up: float, prob_down: float) -> float:
    """§30a's documented mapping: ``P(up) - P(down)`` rescaled to [0, 1].

    Result is in [0, 1] whenever prob_up and prob_down are each in [0, 1] --
    the difference is in [-1, 1], and ``(x + 1) / 2`` maps that onto [0, 1]
    with 0.5 as neutral, matching every other fusion component's scale.
    """
    return (prob_up - prob_down + 1.0) / 2.0


def confidence_from_probabilities(proba_row: np.ndarray) -> float:
    """How concentrated the prediction is: the top class's probability.

    A simple, defensible choice for Phase 9 -- distinguishable from
    fusion_score (which carries direction) because confidence is symmetric:
    a confident DOWN call and a confident UP call have the same confidence.
    """
    return float(np.max(proba_row))


async def _load_latest_feature_row(
    session: AsyncSession, *, symbol: str, timeframe: str, feature_version: str
) -> tuple[datetime, dict[str, Any]] | None:
    row = (
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
    return (row.open_time, row.features) if row is not None else None


async def predict_latest(
    session: AsyncSession,
    *,
    model_id: str,
    version: str,
    models_root: Path,
) -> ModelPrediction | None:
    """Run inference on the most recent feature row for a registered model.

    Returns ``None`` (storing nothing) if there is no feature row yet, or if
    that row is missing a value the model needs -- an incomplete prediction is
    never stored as if it were real (§96).
    """
    registry_row = (
        await session.execute(
            select(ModelVersion).where(
                ModelVersion.model_id == model_id, ModelVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if registry_row is None:
        raise NotFoundError(f"No registered model {model_id}:{version}.")
    if registry_row.symbol is None or registry_row.timeframe is None:
        raise ValidationError(f"Model {model_id}:{version} has no symbol/timeframe to predict on.")

    artifact_path = Path(registry_row.artifact_path)
    if not artifact_path.is_absolute():
        artifact_path = models_root / artifact_path
    model = load(artifact_path.parent)

    latest = await _load_latest_feature_row(
        session,
        symbol=registry_row.symbol,
        timeframe=registry_row.timeframe,
        feature_version=registry_row.feature_version,
    )
    if latest is None:
        return None
    open_time, raw_features = latest

    encoded = encode_features(raw_features)
    row_df = pd.DataFrame([encoded])
    missing_or_nan = [
        col for col in model.feature_columns
        if col not in row_df.columns or pd.isna(row_df[col].iloc[0])
    ]
    if missing_or_nan:
        return None  # not enough history yet for this model's own inputs

    proba = predict_proba(model, row_df)[0]
    classes = predicted_class_probabilities(proba)
    fusion_score = fusion_score_from_probabilities(classes["prob_up"], classes["prob_down"])
    confidence = confidence_from_probabilities(proba)

    prediction = ModelPrediction(
        model_id=model_id,
        model_version=version,
        feature_version=registry_row.feature_version,
        symbol=registry_row.symbol,
        timeframe=registry_row.timeframe,
        open_time=open_time,
        predicted_at=utc_now(),
        prob_up=classes["prob_up"],
        prob_neutral=classes["prob_neutral"],
        prob_down=classes["prob_down"],
        fusion_score=fusion_score,
        confidence=confidence,
        shadow_mode=True,
    )

    stmt = pg_insert(ModelPrediction).values(
        model_id=prediction.model_id,
        model_version=prediction.model_version,
        feature_version=prediction.feature_version,
        symbol=prediction.symbol,
        timeframe=prediction.timeframe,
        open_time=prediction.open_time,
        predicted_at=prediction.predicted_at,
        prob_up=prediction.prob_up,
        prob_neutral=prediction.prob_neutral,
        prob_down=prediction.prob_down,
        fusion_score=prediction.fusion_score,
        confidence=prediction.confidence,
        shadow_mode=prediction.shadow_mode,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_model_predictions_model_version",
        set_={
            "predicted_at": stmt.excluded.predicted_at,
            "prob_up": stmt.excluded.prob_up,
            "prob_neutral": stmt.excluded.prob_neutral,
            "prob_down": stmt.excluded.prob_down,
            "fusion_score": stmt.excluded.fusion_score,
            "confidence": stmt.excluded.confidence,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return prediction
