"""ML evaluation metrics for a 3-class model (§84, §85).

Trading metrics (net return, Sharpe, drawdown, profit factor, expectancy —
the actual deciding factor for promotion per §84) require the backtesting
engine, which does not exist yet (Phase 12).  This module covers only the ML
side: accuracy, precision/recall/F1, ROC-AUC (one-vs-rest, "where meaningful"
per §84 — degenerate if a class is entirely absent from a small evaluation
window), log loss, and Brier score as the calibration check §85 requires.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)

from app.ml.labeling import LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP

CLASS_LABELS = [LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP]
CLASS_NAMES = {LABEL_DOWN: "down", LABEL_NEUTRAL: "neutral", LABEL_UP: "up"}


def brier_score_multiclass(y_true: np.ndarray, proba: np.ndarray) -> float:
    """Mean squared error between the one-hot true label and the predicted
    probability vector, averaged over classes and samples.

    This is the multiclass generalisation of the standard binary Brier score:
    lower is better-calibrated, 0 is a perfect probabilistic forecast.
    """
    one_hot = np.zeros_like(proba)
    for row, label in enumerate(y_true):
        one_hot[row, int(label)] = 1.0
    return float(np.mean(np.sum((proba - one_hot) ** 2, axis=1)))


def evaluate(y_true: np.ndarray, proba: np.ndarray) -> dict[str, Any]:
    """Every §84/§85 ML metric this system currently computes, as one dict
    ready to store in ``ModelMetric.metrics``.
    """
    predicted = proba.argmax(axis=1)
    present_classes = sorted({int(c) for c in np.unique(y_true)})

    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, predicted, labels=CLASS_LABELS, zero_division=0
    )

    result: dict[str, Any] = {
        "sample_count": int(len(y_true)),
        "accuracy": float(accuracy_score(y_true, predicted)),
        "macro_f1": float(
            f1_score(y_true, predicted, labels=CLASS_LABELS, average="macro", zero_division=0)
        ),
        "log_loss": float(log_loss(y_true, proba, labels=CLASS_LABELS)),
        "brier_score": brier_score_multiclass(y_true, proba),
        "per_class": {
            CLASS_NAMES[label]: {
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
            for i, label in enumerate(CLASS_LABELS)
        },
    }

    # ROC-AUC is undefined for a class that never appears in y_true; report it
    # only when every class is present rather than raising or fabricating a
    # value (§84 "where meaningful").
    if len(present_classes) == len(CLASS_LABELS):
        result["roc_auc_ovr_macro"] = float(
            roc_auc_score(y_true, proba, labels=CLASS_LABELS, multi_class="ovr", average="macro")
        )
    else:
        result["roc_auc_ovr_macro"] = None
        result["roc_auc_note"] = (
            f"Not computed: only classes {present_classes} present in this evaluation window."
        )

    return result


def passes_minimum_bar(
    metrics: dict[str, Any], *, min_accuracy: float, min_macro_f1: float
) -> bool:
    """Whether ML metrics alone clear the bar for CANDIDATE -> VALIDATED.

    This is deliberately not a promotion-to-PRODUCTION decision: §84 states
    trading metrics are the deciding factor for that, and no backtest exists
    yet to produce them (Phase 12).
    """
    return metrics["accuracy"] >= min_accuracy and metrics["macro_f1"] >= min_macro_f1
