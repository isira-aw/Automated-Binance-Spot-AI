"""Model registry, predictions, metrics and training-run tables (§37, §39)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class ModelVersion(Base, TimestampMixin):
    """One entry in the model registry.

    ``artifact_path`` points at a file under ``models/`` on the persistent
    volume.  Startup verifies the artifact exists before a model may be treated
    as PRODUCTION — a registry row without its artifact is a hard error (§112).
    """

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)  # LIGHTGBM | ...
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(8))
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    preprocessing_path: Mapped[str | None] = mapped_column(Text)
    training_data_range: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_range: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    test_range: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hyperparameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("model_id", "version", name="uq_model_versions_model_id"),
    )


class ModelPrediction(Base):
    """Every prediction, including shadow-mode ones that never trade (§26)."""

    __tablename__ = "model_predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    prob_up: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False)
    prob_neutral: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False)
    prob_down: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False)
    # Class probabilities mapped onto the unified [0,1] fusion scale (§30a).
    fusion_score: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    shadow_mode: Mapped[bool] = mapped_column(nullable=False, default=False)
    realised_label: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "model_version", "symbol", "timeframe", "open_time",
            name="uq_model_predictions_model_version",
        ),
        Index("ix_model_predictions_symbol_time", "symbol", "predicted_at"),
    )


class ModelMetric(Base):
    """Evaluation metrics per model version and evaluation window (§84, §85)."""

    __tablename__ = "model_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metric_set: Mapped[str] = mapped_column(String(32), nullable=False)  # ML | TRADING | CALIBRATION
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class TrainingRun(Base, TimestampMixin):
    """Experiment log — every run, including rejected ones (§22, §36).

    Recording failures as well as successes is what makes repeated-optimisation
    (p-hacking) visible after the fact.
    """

    __tablename__ = "training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    experiment_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="TRAINING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_range: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resulting_model_version: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
