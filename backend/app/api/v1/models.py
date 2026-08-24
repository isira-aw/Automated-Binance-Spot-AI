"""Model registry namespace: read the registry, trigger training, predict (§39, §59).

Replaces the ``models`` entry in ``not_implemented.py`` now that Phase 9
builds the LightGBM baseline.  Full auto-retraining/promotion-to-PRODUCTION
stays out of scope (Phase 38, Tier 2, and Phase 12's backtest respectively) —
this namespace only covers what the baseline training pipeline can honestly
support today.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.v1.deps import SessionDep, SettingsDep
from app.core.errors import ValidationError
from app.core.logging_config import get_logger
from app.database.session import session_scope
from app.ml.prediction import predict_latest
from app.ml.training import TrainingOutcome, get_training_tracker, run_training_job
from app.models.ml import ModelVersion
from app.schemas.models import (
    ModelVersionOut,
    PredictionOut,
    TrainingOutcomeOut,
    TrainingStatusOut,
    TrainRequest,
)

logger = get_logger("api.models")
router = APIRouter(prefix="/models", tags=["models"])


def _to_out(row: ModelVersion) -> ModelVersionOut:
    return ModelVersionOut(
        model_id=row.model_id,
        version=row.version,
        model_type=row.model_type,
        status=row.status,
        symbol=row.symbol,
        timeframe=row.timeframe,
        feature_version=row.feature_version,
        artifact_sha256=row.artifact_sha256,
        training_data_range=row.training_data_range,
        validation_range=row.validation_range,
        test_range=row.test_range,
        hyperparameters=row.hyperparameters,
        metrics=row.metrics,
        created_at=row.created_at,
        promoted_at=row.promoted_at,
        notes=row.notes,
    )


@router.get("", response_model=list[ModelVersionOut], summary="Model registry")
async def list_models(
    session: SessionDep,
    symbol: str | None = Query(None),
    status: str | None = Query(None),
) -> list[ModelVersionOut]:
    query = select(ModelVersion).order_by(ModelVersion.created_at.desc())
    if symbol:
        query = query.where(ModelVersion.symbol == symbol.upper())
    if status:
        query = query.where(ModelVersion.status == status.upper())
    rows = (await session.execute(query)).scalars().all()
    return [_to_out(row) for row in rows]


@router.post(
    "/train",
    response_model=TrainingOutcomeOut,
    status_code=202,
    summary="Train a LightGBM baseline",
)
async def start_training(request: TrainRequest, settings: SettingsDep) -> TrainingOutcomeOut:
    """Kick off training in the background and return immediately (§76).

    Only one training job runs at a time -- concurrent LightGBM training runs
    would contend for the same CPU cores for no benefit on a laptop (§52).

    The job id is generated here, before the background task starts, so the
    202 response can actually be correlated with what ``GET /train/status``
    reports later -- generating it inside the task would leave the caller
    with no way to tell "my request" apart from a previous one.
    """
    tracker = get_training_tracker()
    if tracker.running:
        raise ValidationError("A training job is already running.")

    job_id = uuid.uuid4().hex
    tracker.running = True
    task = asyncio.create_task(
        _run_and_track(job_id, request.symbol.upper(), request.timeframe, settings),
        name="model-training",
    )
    tracker.background_task = task
    task.add_done_callback(lambda _: setattr(tracker, "background_task", None))

    return TrainingOutcomeOut(
        job_id=job_id, status="RUNNING", model_version=None, registry_status=None,
        error=None, metrics=None,
    )


async def _run_and_track(job_id: str, symbol: str, timeframe: str, settings) -> None:
    tracker = get_training_tracker()
    try:
        async with session_scope() as session:
            outcome = await run_training_job(
                session, settings, symbol=symbol, timeframe=timeframe, job_id=job_id
            )
        tracker.current = outcome
    except Exception as exc:
        logger.error(
            "Training request failed outside the recorded job",
            extra={"event_type": "training_request_failed", "job_id": job_id},
            exc_info=exc,
        )
        from app.models.enums import JobStatus

        tracker.current = TrainingOutcome(job_id=job_id, status=JobStatus.FAILED, error=str(exc))
    finally:
        tracker.running = False


@router.get("/train/status", response_model=TrainingStatusOut, summary="Training job status")
async def training_status() -> TrainingStatusOut:
    tracker = get_training_tracker()
    outcome = tracker.current
    return TrainingStatusOut(
        running=tracker.running,
        outcome=(
            TrainingOutcomeOut(
                job_id=outcome.job_id,
                status=outcome.status.value,
                model_version=outcome.model_version,
                registry_status=outcome.registry_status.value if outcome.registry_status else None,
                error=outcome.error,
                metrics=outcome.metrics,
            )
            if outcome is not None
            else None
        ),
    )


@router.get(
    "/{model_id}/{version}", response_model=ModelVersionOut, summary="One registry entry"
)
async def get_model(session: SessionDep, model_id: str, version: str) -> ModelVersionOut:
    row = (
        await session.execute(
            select(ModelVersion).where(
                ModelVersion.model_id == model_id, ModelVersion.version == version
            )
        )
    ).scalar_one_or_none()
    if row is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"No registered model {model_id}:{version}.")
    return _to_out(row)


@router.post(
    "/{model_id}/{version}/predict",
    response_model=PredictionOut | None,
    summary="Run inference on the latest feature row",
)
async def run_prediction(
    session: SessionDep, settings: SettingsDep, model_id: str, version: str
) -> PredictionOut | None:
    prediction = await predict_latest(
        session, model_id=model_id, version=version, models_root=settings.paths.root
    )
    if prediction is None:
        return None
    return PredictionOut(
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
