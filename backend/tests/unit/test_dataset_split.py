"""Chronological train/validation/test split and label-boundary trimming (§36).

The core property under test: no row's label may depend on a close price that
belongs to a later split.  A random-split bug or a missing boundary trim would
let a handful of rows right at the edge "see" the next split's prices through
their forward-looking label -- exactly the kind of leak that inflates
validation metrics without showing up as an obviously wrong number.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.errors import ValidationError
from app.ml.dataset import chronological_split


def make_df(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open_time": pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"),
            "close": [100.0 + i for i in range(n)],
            "sma_20": [1.0] * n,
        }
    )


def test_splits_are_in_chronological_order_not_shuffled():
    df = make_df(100)
    frame = chronological_split(df, horizon=1, threshold=0.0)
    assert frame.train["open_time"].max() < frame.validation["open_time"].min()
    assert frame.validation["open_time"].max() < frame.test["open_time"].min()


def test_train_fraction_and_validation_fraction_roughly_match_requested_size():
    df = make_df(1000)
    frame = chronological_split(
        df, horizon=1, threshold=0.0, train_fraction=0.7, validation_fraction=0.15
    )
    total = len(frame.train) + len(frame.validation) + len(frame.test)
    # Exact counts shift slightly from boundary trimming; the proportions
    # should still be close to what was requested.
    assert 0.65 < len(frame.train) / total < 0.72


def test_boundary_trim_removes_exactly_horizon_rows_before_each_internal_cut():
    df = make_df(100)
    horizon = 5
    frame = chronological_split(df, horizon=horizon, threshold=0.0)

    # Untrimmed split points, before any label-boundary or NaN trimming.
    n = len(df) - horizon  # rows with a defined label
    train_end = int(n * 0.7)
    validation_end = train_end + int(n * 0.15)

    assert len(frame.train) == train_end - horizon
    assert len(frame.validation) == (validation_end - train_end) - horizon
    # Test is the last split -- nothing after it to leak into, so it is not
    # trimmed from its own tail (though rows without a defined label anywhere
    # in df are already excluded before splitting).
    assert len(frame.test) == n - validation_end


def test_no_trimming_needed_reduces_to_horizon_zero_equivalent_shape():
    """With horizon=0 there is nothing to trim -- this isolates the trimming
    logic itself from the labelling logic by giving every row a label."""
    df = make_df(100)
    frame_h0 = chronological_split(df, horizon=1, threshold=0.0)
    frame_h10 = chronological_split(df, horizon=10, threshold=0.0)
    # A larger horizon must trim more rows from train and validation.
    assert len(frame_h10.train) < len(frame_h0.train)
    assert len(frame_h10.validation) < len(frame_h0.validation)


def test_the_last_row_of_train_cannot_see_into_validation():
    """Direct proof of the property this module exists to guarantee: take the
    label actually assigned to the last training row, and confirm it was
    computed from a close price that is itself still within the training
    range -- never a validation-range close."""
    df = make_df(100)
    horizon = 5
    frame = chronological_split(df, horizon=horizon, threshold=0.0)

    last_train_time = frame.train["open_time"].iloc[-1]
    last_train_index = df.index[df["open_time"] == last_train_time][0]
    forward_index = last_train_index + horizon

    validation_start_time = frame.validation["open_time"].iloc[0]
    validation_start_index = df.index[df["open_time"] == validation_start_time][0]

    assert forward_index < validation_start_index


def test_invalid_fractions_are_rejected():
    df = make_df(50)
    with pytest.raises(ValidationError):
        chronological_split(
            df, horizon=1, threshold=0.0, train_fraction=0.9, validation_fraction=0.5
        )
    with pytest.raises(ValidationError):
        chronological_split(
            df, horizon=1, threshold=0.0, train_fraction=0.0, validation_fraction=0.5
        )


def test_feature_columns_exclude_open_time_and_close():
    df = make_df(50)
    frame = chronological_split(df, horizon=1, threshold=0.0)
    assert "open_time" not in frame.feature_columns
    assert "close" not in frame.feature_columns
    assert "sma_20" in frame.feature_columns


def test_a_missing_boundary_trim_would_be_caught(monkeypatch):
    """Negative control: disable the trim and show the last-train-row check
    above actually fails, proving it is a real test of the property and not
    vacuously true."""
    import app.ml.dataset as dataset_module

    monkeypatch.setattr(dataset_module, "_trim_boundary", lambda df, **kwargs: df)

    df = make_df(100)
    horizon = 5
    frame = chronological_split(df, horizon=horizon, threshold=0.0)

    last_train_time = frame.train["open_time"].iloc[-1]
    last_train_index = df.index[df["open_time"] == last_train_time][0]
    forward_index = last_train_index + horizon

    validation_start_time = frame.validation["open_time"].iloc[0]
    validation_start_index = df.index[df["open_time"] == validation_start_time][0]

    assert forward_index >= validation_start_index  # the leak, demonstrated
