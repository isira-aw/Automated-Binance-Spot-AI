"""Loads persisted features and builds a chronologically-split training frame.

Walk-forward, never random (§36): the split is a single forward chain
TRAIN -> VALIDATE -> TEST in time order.  The subtler leak this module guards
against is at the *boundary*: a label's forward-return window (§ labeling.py)
can reach past a split edge and see into the next split's price data.  Rows
whose label window would cross a boundary are dropped from the split that
would otherwise "borrow" that information, rather than silently letting a
few boundary rows leak a handful of future closes into training.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.ml.labeling import make_labels
from app.models.market import Candle, TechnicalFeature

# Structure fields are boolean/string; encoded numerically here so every
# training column is a plain float, which is what LightGBM's low-level API
# expects and what makes the feature-column contract in lightgbm_model.py
# simple to validate against (§78).
_STRUCTURE_TREND_ENCODING = {"BULLISH": 1.0, "BEARISH": -1.0, "UNKNOWN": 0.0}


@dataclass
class TrainingFrame:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    feature_columns: list[str]
    label_column: str = "label"

    def is_empty(self) -> bool:
        return self.train.empty or self.validation.empty or self.test.empty


def encode_features(raw: dict[str, object]) -> dict[str, float]:
    encoded: dict[str, float] = {}
    for key, value in raw.items():
        if key == "structure_trend":
            encoded[key] = _STRUCTURE_TREND_ENCODING.get(str(value), 0.0)
        elif isinstance(value, bool):
            encoded[key] = 1.0 if value else 0.0
        elif value is None:
            encoded[key] = np.nan
        else:
            encoded[key] = float(value)
    return encoded


async def _load_features_and_closes(
    session: AsyncSession, *, symbol: str, timeframe: str, feature_version: str
) -> pd.DataFrame:
    feature_rows = (
        (
            await session.execute(
                select(TechnicalFeature)
                .where(
                    TechnicalFeature.symbol == symbol,
                    TechnicalFeature.timeframe == timeframe,
                    TechnicalFeature.feature_version == feature_version,
                )
                .order_by(TechnicalFeature.open_time)
            )
        )
        .scalars()
        .all()
    )
    if not feature_rows:
        return pd.DataFrame()

    candle_rows = (
        (
            await session.execute(
                select(Candle.open_time, Candle.close)
                .where(
                    Candle.symbol == symbol,
                    Candle.timeframe == timeframe,
                    Candle.is_closed.is_(True),
                )
                .order_by(Candle.open_time)
            )
        )
        .all()
    )
    closes = {row.open_time: float(row.close) for row in candle_rows}

    records = []
    for row in feature_rows:
        close = closes.get(row.open_time)
        if close is None:
            continue  # a feature row with no matching closed candle is unusable
        record = encode_features(row.features)
        record["open_time"] = row.open_time
        record["close"] = close
        records.append(record)

    return pd.DataFrame.from_records(records).sort_values("open_time").reset_index(drop=True)


def _trim_boundary(df: pd.DataFrame, *, horizon: int, is_before_boundary: bool) -> pd.DataFrame:
    """Drop rows whose label window would cross into the neighbouring split."""
    if horizon <= 0 or df.empty:
        return df
    return df.iloc[:-horizon] if is_before_boundary else df


def chronological_split(
    df: pd.DataFrame,
    *,
    horizon: int,
    threshold: float,
    train_fraction: float = 0.7,
    validation_fraction: float = 0.15,
) -> TrainingFrame:
    """Split ``df`` (already sorted by ``open_time``) into TRAIN/VALIDATE/TEST.

    Splitting happens before labelling only in the sense that the boundary
    trim below removes exactly the rows whose label would otherwise reach
    across the cut -- the label itself is computed once, over the whole
    series, so a bar's label never depends on which split it lands in.
    """
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValidationError("train_fraction and validation_fraction must be in (0, 1).")
    if train_fraction + validation_fraction >= 1:
        raise ValidationError("train_fraction + validation_fraction must be < 1.")

    labelled = df.copy()
    labelled["label"] = make_labels(labelled["close"], horizon=horizon, threshold=threshold)
    labelled = labelled.dropna(subset=["label"]).reset_index(drop=True)

    n = len(labelled)
    train_end = int(n * train_fraction)
    validation_end = train_end + int(n * validation_fraction)

    train = _trim_boundary(labelled.iloc[:train_end], horizon=horizon, is_before_boundary=True)
    validation = _trim_boundary(
        labelled.iloc[train_end:validation_end], horizon=horizon, is_before_boundary=True
    )
    test = labelled.iloc[validation_end:]

    feature_columns = [
        col for col in df.columns if col not in {"open_time", "close"}
    ]

    return TrainingFrame(
        train=train, validation=validation, test=test, feature_columns=feature_columns
    )


async def build_training_frame(
    session: AsyncSession,
    *,
    symbol: str,
    timeframe: str,
    feature_version: str,
    horizon: int,
    threshold: float,
    train_fraction: float = 0.7,
    validation_fraction: float = 0.15,
) -> TrainingFrame:
    df = await _load_features_and_closes(
        session, symbol=symbol, timeframe=timeframe, feature_version=feature_version
    )
    if df.empty:
        return TrainingFrame(
            train=pd.DataFrame(), validation=pd.DataFrame(), test=pd.DataFrame(), feature_columns=[]
        )
    return chronological_split(
        df,
        horizon=horizon,
        threshold=threshold,
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
    )
