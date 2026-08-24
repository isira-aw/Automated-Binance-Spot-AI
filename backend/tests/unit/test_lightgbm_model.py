"""LightGBM training, artifact round-trip, and the feature-column contract (§77, §78)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ValidationError
from app.ml.labeling import LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP
from app.ml.lightgbm_model import load, predict_proba, predicted_class_probabilities, save, train


def learnable_dataset(n: int = 600, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """A dataset where the label is a deterministic function of one feature,
    so a correctly-wired training pipeline should predict it near-perfectly --
    this isolates "is the plumbing correct" from "is this a good trading
    model," which is not what Phase 9 needs to prove."""
    rng = np.random.default_rng(seed)
    signal = rng.normal(0, 1, n)
    noise = rng.normal(0, 1, n)
    labels = np.where(signal > 0.5, LABEL_UP, np.where(signal < -0.5, LABEL_DOWN, LABEL_NEUTRAL))

    df = pd.DataFrame({"signal_feature": signal, "noise_feature": noise, "label": labels})
    split = int(n * 0.8)
    return df.iloc[:split].reset_index(drop=True), df.iloc[split:].reset_index(drop=True), [
        "signal_feature",
        "noise_feature",
    ]


def test_training_learns_a_clean_deterministic_signal():
    train_df, val_df, columns = learnable_dataset()
    model = train(train_df, val_df, feature_columns=columns, num_boost_round=100)
    proba = predict_proba(model, val_df)
    predicted = proba.argmax(axis=1)
    accuracy = (predicted == val_df["label"].to_numpy()).mean()
    assert accuracy > 0.9


def test_probability_rows_sum_to_one():
    train_df, val_df, columns = learnable_dataset()
    model = train(train_df, val_df, feature_columns=columns, num_boost_round=20)
    proba = predict_proba(model, val_df)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0, atol=1e-6)


def test_predicted_class_probabilities_maps_columns_to_named_classes():
    row = np.array([0.7, 0.2, 0.1])
    result = predicted_class_probabilities(row)
    assert result == {"prob_down": 0.7, "prob_neutral": 0.2, "prob_up": 0.1}


def test_training_is_deterministic_given_the_same_seed():
    train_df, val_df, columns = learnable_dataset()
    model_a = train(train_df, val_df, feature_columns=columns, num_boost_round=50)
    model_b = train(train_df, val_df, feature_columns=columns, num_boost_round=50)
    proba_a = predict_proba(model_a, val_df)
    proba_b = predict_proba(model_b, val_df)
    np.testing.assert_array_equal(proba_a, proba_b)


def test_missing_feature_columns_raise_rather_than_silently_reindexing():
    train_df, val_df, columns = learnable_dataset()
    model = train(train_df, val_df, feature_columns=columns, num_boost_round=10)
    broken = val_df.drop(columns=["noise_feature"])
    with pytest.raises(ValidationError, match="missing feature columns"):
        predict_proba(model, broken)


class TestArtifactRoundTrip:
    def test_save_and_load_reproduces_identical_predictions(self, tmp_path):
        train_df, val_df, columns = learnable_dataset()
        model = train(train_df, val_df, feature_columns=columns, num_boost_round=50)
        before = predict_proba(model, val_df)

        save(model, tmp_path / "v1")
        loaded = load(tmp_path / "v1")
        after = predict_proba(loaded, val_df)

        np.testing.assert_allclose(before, after, atol=1e-9)

    def test_save_writes_a_verifiable_checksum(self, tmp_path):
        train_df, val_df, columns = learnable_dataset()
        model = train(train_df, val_df, feature_columns=columns, num_boost_round=10)
        result = save(model, tmp_path / "v1")

        import hashlib

        digest = hashlib.sha256((tmp_path / "v1" / "model.txt").read_bytes()).hexdigest()
        assert result["sha256"] == digest

    def test_loaded_model_preserves_feature_column_order(self, tmp_path):
        train_df, val_df, columns = learnable_dataset()
        model = train(train_df, val_df, feature_columns=columns, num_boost_round=10)
        save(model, tmp_path / "v1")
        loaded = load(tmp_path / "v1")
        assert loaded.feature_columns == columns

    def test_loading_an_incomplete_directory_fails_loudly(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(ValidationError, match="incomplete"):
            load(tmp_path / "empty")

    def test_a_tampered_feature_column_list_is_rejected_on_load(self, tmp_path):
        """§78: a model must refuse to run against features it wasn't trained
        on, not silently reindex a mismatched column list onto its matrix."""
        train_df, val_df, columns = learnable_dataset()
        model = train(train_df, val_df, feature_columns=columns, num_boost_round=10)
        save(model, tmp_path / "v1")

        import json

        columns_path = tmp_path / "v1" / "feature_columns.json"
        payload = json.loads(columns_path.read_text())
        payload["feature_columns"] = [*payload["feature_columns"], "extra_column"]
        columns_path.write_text(json.dumps(payload))

        with pytest.raises(ValidationError, match="expects"):
            load(tmp_path / "v1")
