"""LightGBM training pipeline orchestration (§37, §39, §80).

DATA -> FEATURE ENGINEERING -> TRAIN -> VALIDATION -> TEST -> MODEL REGISTRY.

The remaining §37 steps -- BACKTEST, OUT-OF-SAMPLE promotion to PRODUCTION,
and PAPER VALIDATION -- need components this system does not have yet (Phase
12, Phase 11).  This pipeline stops at CANDIDATE / VALIDATED, which is as far
as it is honest to go without them: promoting to PRODUCTION on ML metrics
alone would contradict §84's own statement that trading metrics are the
deciding factor.

Every run is recorded in ``training_runs`` — failed and rejected ones too
(§22's p-hacking guard extends naturally to this pipeline: a model that never
got its accuracy above chance is exactly the kind of experiment that must stay
visible, not be quietly discarded).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.logging_config import get_logger
from app.core.time_utils import utc_now
from app.ml import lightgbm_model
from app.ml.dataset import build_training_frame
from app.ml.metrics import evaluate, passes_minimum_bar
from app.models.enums import JobStatus, ModelStatus
from app.models.ml import ModelVersion, TrainingRun

logger = get_logger("ml.training")

MODEL_TYPE = "LIGHTGBM"


@dataclass
class TrainingOutcome:
    job_id: str
    status: JobStatus
    model_version: str | None = None
    registry_status: ModelStatus | None = None
    error: str | None = None
    metrics: dict[str, object] | None = None


def _model_id(symbol: str, timeframe: str) -> str:
    return f"lightgbm_{symbol.lower()}_{timeframe}"


async def run_training_job(
    session: AsyncSession,
    settings: Settings,
    *,
    symbol: str,
    timeframe: str,
    job_id: str | None = None,
) -> TrainingOutcome:
    job_id = job_id or uuid.uuid4().hex
    model_id = _model_id(symbol, timeframe)
    started_at = utc_now()

    run = TrainingRun(
        job_id=job_id,
        model_id=model_id,
        model_type=MODEL_TYPE,
        status=JobStatus.RUNNING.value,
        experiment_kind="TRAINING",
        started_at=started_at,
        parameters={
            "label_horizon": settings.models.label_horizon,
            "label_threshold": settings.models.label_threshold,
            "train_fraction": settings.models.train_fraction,
            "validation_fraction": settings.models.validation_fraction,
            "feature_version": settings.models.feature_version,
        },
    )
    session.add(run)
    await session.commit()

    try:
        outcome = await _train_and_register(
            session, settings, symbol=symbol, timeframe=timeframe, job_id=job_id
        )
    except Exception as exc:
        logger.error(
            "Training job failed",
            extra={"event_type": "training_job_failed", "job_id": job_id, "model_id": model_id},
            exc_info=exc,
        )
        outcome = TrainingOutcome(job_id=job_id, status=JobStatus.FAILED, error=str(exc))

    run.status = outcome.status.value
    run.finished_at = utc_now()
    run.resulting_model_version = outcome.model_version
    run.results = {
        "registry_status": outcome.registry_status.value if outcome.registry_status else None,
        "metrics": outcome.metrics,
    }
    run.error = outcome.error
    await session.commit()

    return outcome


async def _train_and_register(
    session: AsyncSession, settings: Settings, *, symbol: str, timeframe: str, job_id: str
) -> TrainingOutcome:
    model_id = _model_id(symbol, timeframe)
    models = settings.models

    frame = await build_training_frame(
        session,
        symbol=symbol,
        timeframe=timeframe,
        feature_version=models.feature_version,
        horizon=models.label_horizon,
        threshold=models.label_threshold,
        train_fraction=models.train_fraction,
        validation_fraction=models.validation_fraction,
    )
    if frame.is_empty() or len(frame.train) < models.min_training_rows:
        return TrainingOutcome(
            job_id=job_id,
            status=JobStatus.FAILED,
            error=(
                f"Insufficient training data for {symbol}/{timeframe}: "
                f"{len(frame.train)} training rows, need >= {models.min_training_rows}. "
                "Run a backfill and let features compute first."
            ),
        )

    trained = lightgbm_model.train(
        frame.train, frame.validation, feature_columns=frame.feature_columns
    )

    validation_metrics = evaluate(
        frame.validation["label"].to_numpy(),
        lightgbm_model.predict_proba(trained, frame.validation),
    )
    test_metrics = evaluate(
        frame.test["label"].to_numpy(), lightgbm_model.predict_proba(trained, frame.test)
    )

    version = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    artifact_dir = settings.paths.models_candidates / f"{model_id}_{version}"
    saved = lightgbm_model.save(trained, artifact_dir)

    passes = passes_minimum_bar(
        validation_metrics,
        min_accuracy=models.min_validation_accuracy,
        min_macro_f1=models.min_validation_macro_f1,
    )
    registry_status = ModelStatus.VALIDATED if passes else ModelStatus.CANDIDATE

    registry_row = ModelVersion(
        model_id=model_id,
        version=version,
        model_type=MODEL_TYPE,
        status=registry_status.value,
        symbol=symbol,
        timeframe=timeframe,
        feature_version=models.feature_version,
        artifact_path=str(Path(saved["model_path"]).relative_to(settings.paths.root)),
        artifact_sha256=saved["sha256"],
        preprocessing_path=str(Path(saved["columns_path"]).relative_to(settings.paths.root)),
        training_data_range=_time_range(frame.train),
        validation_range=_time_range(frame.validation),
        test_range=_time_range(frame.test),
        hyperparameters=trained.hyperparameters,
        metrics={"validation": validation_metrics, "test": test_metrics},
        notes=(
            None
            if passes
            else (
                "Did not clear the ML-metric bar for VALIDATED; "
                "kept as CANDIDATE, not deleted (§39)."
            )
        ),
    )
    session.add(registry_row)
    await session.commit()

    logger.info(
        "Training job produced a registered model",
        extra={
            "event_type": "training_job_completed",
            "job_id": job_id,
            "model_id": model_id,
            "model_version": version,
            "registry_status": registry_status.value,
            "validation_accuracy": validation_metrics["accuracy"],
        },
    )

    return TrainingOutcome(
        job_id=job_id,
        status=JobStatus.SUCCEEDED,
        model_version=version,
        registry_status=registry_status,
        metrics={"validation": validation_metrics, "test": test_metrics},
    )


def _time_range(df) -> dict[str, str] | None:
    if df.empty:
        return None
    return {
        "start": df["open_time"].iloc[0].isoformat(),
        "end": df["open_time"].iloc[-1].isoformat(),
        "rows": int(len(df)),
    }


class TrainingJobTracker:
    """In-memory record of the most recent training job (§76).

    Mirrors ``IngestionJobTracker`` in historical_ingestion.py: a restart
    loses this status, but never loses a completed run -- that is already
    durable in ``training_runs`` and ``model_versions``, and the next request
    reads from there, not from this tracker.
    """

    def __init__(self) -> None:
        self.current: TrainingOutcome | None = None
        self.running: bool = False
        self.background_task: object | None = None


_tracker = TrainingJobTracker()


def get_training_tracker() -> TrainingJobTracker:
    return _tracker
