"""ML metric correctness (§84, §85)."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.labeling import LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP
from app.ml.metrics import brier_score_multiclass, evaluate, passes_minimum_bar


def one_hot_proba(labels: list[int]) -> np.ndarray:
    """Perfectly confident (and, if labels match y_true, perfectly correct)
    probability rows."""
    matrix = np.zeros((len(labels), 3))
    for row, label in enumerate(labels):
        matrix[row, label] = 1.0
    return matrix


class TestBrierScore:
    def test_perfect_confident_correct_predictions_score_zero(self):
        y_true = np.array([LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL])
        proba = one_hot_proba([LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL])
        assert brier_score_multiclass(y_true, proba) == pytest.approx(0.0)

    def test_perfect_confident_wrong_predictions_score_two(self):
        """Being maximally confident and maximally wrong is the worst case:
        the one-hot vectors are 1 apart in every differing coordinate, twice
        (once for the true class being 0 instead of 1, once for the predicted
        class being 1 instead of 0) -- MSE of [1,1,0] vs [0,0,1] is 2/3... """
        y_true = np.array([LABEL_UP])
        proba = one_hot_proba([LABEL_DOWN])
        # sum((1-0)^2 + (0-1)^2 + (0-0)^2) = 2, averaged over 1 sample = 2.
        assert brier_score_multiclass(y_true, proba) == pytest.approx(2.0)

    def test_uniform_uncertainty_scores_between_zero_and_two(self):
        y_true = np.array([LABEL_UP, LABEL_DOWN])
        proba = np.full((2, 3), 1 / 3)
        score = brier_score_multiclass(y_true, proba)
        assert 0 < score < 2


class TestEvaluate:
    def test_perfect_predictions_yield_accuracy_one(self):
        y_true = np.array([LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP])
        proba = one_hot_proba([LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP])
        result = evaluate(y_true, proba)
        assert result["accuracy"] == pytest.approx(1.0)
        assert result["macro_f1"] == pytest.approx(1.0)
        assert result["brier_score"] == pytest.approx(0.0)

    def test_roc_auc_is_none_when_a_class_never_appears(self):
        """§84 'where meaningful': ROC-AUC is undefined for an absent class,
        so it must be explicitly None, not a fabricated number."""
        y_true = np.array([LABEL_UP, LABEL_UP, LABEL_NEUTRAL])  # LABEL_DOWN absent
        proba = one_hot_proba([LABEL_UP, LABEL_UP, LABEL_NEUTRAL])
        result = evaluate(y_true, proba)
        assert result["roc_auc_ovr_macro"] is None
        note = result["roc_auc_note"].lower()
        assert "note" in note or "not computed" in note

    def test_roc_auc_is_computed_when_every_class_is_present(self):
        labels = [LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL]
        y_true = np.array(labels)
        proba = one_hot_proba(labels)
        result = evaluate(y_true, proba)
        assert result["roc_auc_ovr_macro"] == pytest.approx(1.0)

    def test_per_class_metrics_cover_every_class_even_if_absent_from_predictions(self):
        y_true = np.array([LABEL_UP, LABEL_UP])
        proba = one_hot_proba([LABEL_UP, LABEL_UP])
        result = evaluate(y_true, proba)
        assert set(result["per_class"]) == {"down", "neutral", "up"}
        assert result["per_class"]["down"]["support"] == 0

    def test_sample_count_matches_input_length(self):
        y_true = np.array([LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL])
        proba = one_hot_proba([LABEL_UP, LABEL_DOWN, LABEL_NEUTRAL])
        assert evaluate(y_true, proba)["sample_count"] == 3


class TestPromotionBar:
    def test_passes_when_both_metrics_clear_the_bar(self):
        metrics = {"accuracy": 0.6, "macro_f1": 0.55}
        assert passes_minimum_bar(metrics, min_accuracy=0.5, min_macro_f1=0.5) is True

    def test_fails_when_accuracy_is_below_the_bar(self):
        metrics = {"accuracy": 0.4, "macro_f1": 0.9}
        assert passes_minimum_bar(metrics, min_accuracy=0.5, min_macro_f1=0.5) is False

    def test_fails_when_macro_f1_is_below_the_bar(self):
        metrics = {"accuracy": 0.9, "macro_f1": 0.3}
        assert passes_minimum_bar(metrics, min_accuracy=0.5, min_macro_f1=0.5) is False
