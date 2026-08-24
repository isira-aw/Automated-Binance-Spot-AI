"""Label generation (§24) — the training target, deliberately forward-looking."""

from __future__ import annotations

import pandas as pd
import pytest

from app.ml.labeling import LABEL_DOWN, LABEL_NEUTRAL, LABEL_UP, make_labels


def test_a_move_above_threshold_is_labelled_up():
    close = pd.Series([100.0, 100.0, 100.0, 106.0])
    labels = make_labels(close, horizon=1, threshold=0.01)
    assert labels.iloc[2] == LABEL_UP  # (106-100)/100 = 6% > 1%


def test_a_move_below_threshold_is_labelled_down():
    close = pd.Series([100.0, 100.0, 100.0, 94.0])
    labels = make_labels(close, horizon=1, threshold=0.01)
    assert labels.iloc[2] == LABEL_DOWN


def test_a_small_move_is_labelled_neutral():
    close = pd.Series([100.0, 100.0, 100.0, 100.3])
    labels = make_labels(close, horizon=1, threshold=0.01)
    assert labels.iloc[2] == LABEL_NEUTRAL


def test_move_exactly_at_the_threshold_is_neutral_not_up():
    close = pd.Series([100.0, 101.0])
    labels = make_labels(close, horizon=1, threshold=0.01)
    assert labels.iloc[0] == LABEL_NEUTRAL


def test_the_last_horizon_rows_have_no_label():
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0])
    labels = make_labels(close, horizon=2, threshold=0.01)
    assert labels.iloc[-2:].isna().all()
    assert labels.iloc[:-2].notna().all()


def test_horizon_must_be_positive():
    with pytest.raises(ValueError, match="horizon"):
        make_labels(pd.Series([1.0, 2.0]), horizon=0, threshold=0.01)


def test_threshold_must_be_non_negative():
    with pytest.raises(ValueError, match="threshold"):
        make_labels(pd.Series([1.0, 2.0]), horizon=1, threshold=-0.01)


def test_zero_threshold_never_produces_neutral_on_nonzero_moves():
    close = pd.Series([100.0, 100.01, 99.99])
    labels = make_labels(close, horizon=1, threshold=0.0)
    assert labels.iloc[0] == LABEL_UP
    assert labels.iloc[1] == LABEL_DOWN


def test_a_longer_horizon_looks_further_ahead_not_at_the_next_bar():
    close = pd.Series([100.0, 200.0, 100.0, 100.0, 150.0])
    horizon1 = make_labels(close, horizon=1, threshold=0.01)
    horizon3 = make_labels(close, horizon=3, threshold=0.01)
    # horizon=1 at bar 0 compares to bar 1 (100->200, big UP move).
    assert horizon1.iloc[0] == LABEL_UP
    # horizon=3 at bar 0 compares to bar 3 (100->100, neutral) -- a different
    # bar entirely, proving the horizon parameter actually changes the target.
    assert horizon3.iloc[0] == LABEL_NEUTRAL
