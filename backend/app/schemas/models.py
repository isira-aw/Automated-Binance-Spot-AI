"""Schemas for the model registry namespace (§39, §59)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ModelVersionOut(BaseModel):
    model_id: str
    version: str
    model_type: str
    status: str
    symbol: str | None
    timeframe: str | None
    feature_version: str
    artifact_sha256: str | None
    training_data_range: dict[str, Any] | None
    validation_range: dict[str, Any] | None
    test_range: dict[str, Any] | None
    hyperparameters: dict[str, Any] | None
    metrics: dict[str, Any] | None
    created_at: datetime
    promoted_at: datetime | None
    notes: str | None


class TrainRequest(BaseModel):
    symbol: str
    timeframe: str


class TrainingOutcomeOut(BaseModel):
    job_id: str
    status: str
    model_version: str | None
    registry_status: str | None
    error: str | None
    metrics: dict[str, Any] | None


class TrainingStatusOut(BaseModel):
    running: bool
    outcome: TrainingOutcomeOut | None


class PredictionOut(BaseModel):
    model_id: str
    model_version: str
    feature_version: str
    symbol: str
    timeframe: str
    open_time: datetime
    predicted_at: datetime
    prob_up: float
    prob_neutral: float
    prob_down: float
    fusion_score: float
    confidence: float
    shadow_mode: bool
