"""LightGBM baseline model: train, persist, load, predict (§24, §77, §78).

Uses the low-level ``lgb.train``/``Booster`` API rather than the sklearn
wrapper.  With ``objective="multiclass"`` and integer labels in
``[0, num_class)``, the Booster's predicted probability columns are in class-
index order by construction — no label encoder involved, so there is no
version-dependent object to keep in sync with ``labeling.py``'s class
constants across a save/load round trip.  The native text format
(``save_model``/``Booster(model_file=...)``) is portable and human-readable,
which is worth more for an audited trading system than the smaller size of a
pickle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from app.core.errors import ValidationError
from app.ml.labeling import LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP

NUM_CLASSES = 3

DEFAULT_HYPERPARAMETERS: dict[str, Any] = {
    "objective": "multiclass",
    "num_class": NUM_CLASSES,
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "seed": 42,
    "deterministic": True,
    "verbose": -1,
}


@dataclass
class TrainedModel:
    booster: lgb.Booster
    feature_columns: list[str]
    hyperparameters: dict[str, Any]
    best_iteration: int


def _to_matrix(df: pd.DataFrame, feature_columns: list[str]) -> np.ndarray:
    missing = [col for col in feature_columns if col not in df.columns]
    if missing:
        raise ValidationError(f"Training frame is missing feature columns: {missing}")
    return df[feature_columns].to_numpy(dtype=np.float64)


def train(
    train_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    *,
    feature_columns: list[str],
    label_column: str = "label",
    hyperparameters: dict[str, Any] | None = None,
    num_boost_round: int = 500,
    early_stopping_rounds: int = 30,
) -> TrainedModel:
    """Fit on ``train_df``, using ``validation_df`` only for early stopping.

    Early stopping means the validation split does influence which iteration
    is kept, which is why final promotion decisions in this system read the
    held-out test split's metrics, not the validation split's (§36, §37).
    """
    params = dict(DEFAULT_HYPERPARAMETERS)
    if hyperparameters:
        params.update(hyperparameters)
    params["num_class"] = NUM_CLASSES  # never overridable: fixed 3-class target

    x_train = _to_matrix(train_df, feature_columns)
    y_train = train_df[label_column].to_numpy(dtype=np.int32)
    x_val = _to_matrix(validation_df, feature_columns)
    y_val = validation_df[label_column].to_numpy(dtype=np.int32)

    train_set = lgb.Dataset(x_train, label=y_train, feature_name=feature_columns)
    val_set = lgb.Dataset(x_val, label=y_val, feature_name=feature_columns, reference=train_set)

    booster = lgb.train(
        params,
        train_set,
        num_boost_round=num_boost_round,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False)],
    )

    return TrainedModel(
        booster=booster,
        feature_columns=feature_columns,
        hyperparameters=params,
        best_iteration=booster.best_iteration,
    )


def predict_proba(model: TrainedModel, df: pd.DataFrame) -> np.ndarray:
    """Class probabilities in ``[P(down), P(neutral), P(up)]`` order per row."""
    matrix = _to_matrix(df, model.feature_columns)
    return model.booster.predict(matrix, num_iteration=model.best_iteration)


def save(model: TrainedModel, directory: Path) -> dict[str, str]:
    """Persist the booster and its feature-column contract.

    Returns the sha256 of the model file, for the registry's artifact-
    integrity check (§39, §112) to verify against later.
    """
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / "model.txt"
    columns_path = directory / "feature_columns.json"

    model.booster.save_model(str(model_path), num_iteration=model.best_iteration)
    columns_path.write_text(
        json.dumps(
            {"feature_columns": model.feature_columns, "hyperparameters": model.hyperparameters},
            indent=2,
        )
    )

    digest = hashlib.sha256()
    with model_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return {
        "model_path": str(model_path),
        "columns_path": str(columns_path),
        "sha256": digest.hexdigest(),
    }


def load(directory: Path) -> TrainedModel:
    """Load a booster and re-assert its exact feature-column contract (§78).

    The column list is not just metadata here -- ``predict_proba`` builds its
    input matrix by indexing ``df[model.feature_columns]``, so if the
    persisted order does not match what training used, predictions would be
    silently computed against the wrong columns rather than failing loudly.
    """
    model_path = directory / "model.txt"
    columns_path = directory / "feature_columns.json"
    if not model_path.is_file() or not columns_path.is_file():
        raise ValidationError(f"Model artifact is incomplete at {directory}.")

    booster = lgb.Booster(model_file=str(model_path))
    metadata = json.loads(columns_path.read_text())
    feature_columns = metadata["feature_columns"]

    if booster.num_feature() != len(feature_columns):
        raise ValidationError(
            f"Loaded model expects {booster.num_feature()} features but "
            f"feature_columns.json lists {len(feature_columns)}."
        )

    return TrainedModel(
        booster=booster,
        feature_columns=feature_columns,
        hyperparameters=metadata.get("hyperparameters", {}),
        best_iteration=booster.current_iteration(),
    )


def predicted_class_probabilities(row: np.ndarray) -> dict[str, float]:
    """Map a raw probability row to named classes, matching labeling.py."""
    return {
        "prob_down": float(row[LABEL_DOWN]),
        "prob_neutral": float(row[LABEL_NEUTRAL]),
        "prob_up": float(row[LABEL_UP]),
    }
