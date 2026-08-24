"""Supervised labels for the LightGBM baseline (§24).

Unlike every module under ``technical/`` and ``engines/``, labels are
*deliberately* forward-looking — a label is "what actually happened next,"
which is the entire point of a training target. That is not a §18 violation
on its own: the violation would be feeding a label (or anything computed from
it) back in as a *feature* for the same row, which nothing in this module or
``dataset.py`` does. The real leakage risk here is a label whose forward
window crosses a train/validation/test split boundary, which is handled in
``dataset.py``, not here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Class encoding LightGBM is trained against. Fixed and documented because the
# raw integer order is what the low-level Booster API reports probabilities
# in — a wrong assumption here would silently mislabel every prediction.
LABEL_DOWN = 0
LABEL_NEUTRAL = 1
LABEL_UP = 2
LABEL_NAMES = {LABEL_DOWN: "DOWN", LABEL_NEUTRAL: "NEUTRAL", LABEL_UP: "UP"}


def make_labels(
    close: pd.Series, *, horizon: int, threshold: float
) -> pd.Series:
    """Three-class label from the forward return over ``horizon`` bars.

    ``threshold`` is a fractional return (e.g. 0.005 = 0.5%); moves smaller
    than that in either direction are labelled NEUTRAL rather than forcing a
    coin-flip direction onto noise. The last ``horizon`` rows have no future
    bar to look at and are labelled NaN, not guessed.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}.")
    if threshold < 0:
        raise ValueError(f"threshold must be >= 0, got {threshold}.")

    forward_close = close.shift(-horizon)
    forward_return = (forward_close - close) / close

    labels = pd.Series(np.nan, index=close.index, dtype="float64")
    labels[forward_return > threshold] = LABEL_UP
    labels[forward_return < -threshold] = LABEL_DOWN
    labels[(forward_return >= -threshold) & (forward_return <= threshold)] = LABEL_NEUTRAL
    # Rows whose forward window runs past the end of the series never got a
    # forward_return at all (NaN from the shift) and stay NaN here too.
    labels[forward_close.isna()] = np.nan
    return labels
