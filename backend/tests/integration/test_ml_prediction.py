"""Inference against a real trained model and the ModelPrediction upsert (§26, §30a).

Marked ``integration``: requires a reachable PostgreSQL, skipped otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app.core.errors import NotFoundError
from app.ml.prediction import predict_latest
from app.ml.training import run_training_job
from app.models.market import Candle, TechnicalFeature
from app.models.ml import ModelPrediction, ModelVersion, TrainingRun
from app.technical.feature_engine import compute_and_store_all
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    settings = make_settings()
    engine = create_async_engine(settings.database.async_url)
    try:
        async with engine.connect():
            pass
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL is not reachable: {exc}")
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
        for table in (ModelPrediction, TrainingRun, ModelVersion, TechnicalFeature, Candle):
            await session.execute(table.__table__.delete())
        await session.commit()


@pytest.fixture
def small_bar_settings():
    return make_settings(
        models={
            "feature_version": "v1",
            "label_horizon": 3,
            "label_threshold": 0.001,
            "min_training_rows": 50,
            "min_validation_accuracy": 0.0,
            "min_validation_macro_f1": 0.0,
        }
    )


async def _seed_and_train(session, settings) -> tuple[str, str]:
    rng = np.random.default_rng(1)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    count = 300
    trend = np.cumsum(rng.choice([1.0, -1.0], size=count, p=[0.6, 0.4])) * 0.5
    close = 100 + trend + rng.normal(0, 0.3, count)

    session.add_all(
        [
            Candle(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                open_time=start + timedelta(hours=i),
                close_time=start + timedelta(hours=i + 1),
                open=float(close[i]),
                high=float(close[i] + 0.2),
                low=float(close[i] - 0.2),
                close=float(close[i]),
                volume=float(100 + rng.uniform(0, 50)),
                quote_volume=1000.0,
                trades=10,
                is_closed=True,
                source="BINANCE",
            )
            for i in range(count)
        ]
    )
    await session.commit()
    await compute_and_store_all(session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version="v1")

    outcome = await run_training_job(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)
    assert outcome.model_version is not None
    model_id = f"lightgbm_{SYMBOL.lower()}_{TIMEFRAME}"
    return model_id, outcome.model_version


async def test_predict_latest_with_no_registered_model_raises(session, small_bar_settings):
    with pytest.raises(NotFoundError):
        await predict_latest(
            session,
            model_id="lightgbm_btcusdt_1h",
            version="does-not-exist",
            models_root=small_bar_settings.paths.root,
        )


async def test_predict_latest_stores_a_shadow_mode_prediction(session, small_bar_settings):
    model_id, version = await _seed_and_train(session, small_bar_settings)

    prediction = await predict_latest(
        session, model_id=model_id, version=version, models_root=small_bar_settings.paths.root
    )
    assert prediction is not None
    assert prediction.shadow_mode is True
    assert prediction.model_id == model_id
    assert prediction.model_version == version
    assert prediction.symbol == SYMBOL
    assert prediction.timeframe == TIMEFRAME


async def test_prediction_probabilities_sum_to_one(session, small_bar_settings):
    model_id, version = await _seed_and_train(session, small_bar_settings)
    prediction = await predict_latest(
        session, model_id=model_id, version=version, models_root=small_bar_settings.paths.root
    )
    total = prediction.prob_up + prediction.prob_neutral + prediction.prob_down
    assert total == pytest.approx(1.0, abs=1e-4)


async def test_fusion_score_matches_the_documented_mapping(session, small_bar_settings):
    from app.ml.prediction import fusion_score_from_probabilities

    model_id, version = await _seed_and_train(session, small_bar_settings)
    prediction = await predict_latest(
        session, model_id=model_id, version=version, models_root=small_bar_settings.paths.root
    )
    expected = fusion_score_from_probabilities(
        float(prediction.prob_up), float(prediction.prob_down)
    )
    assert float(prediction.fusion_score) == pytest.approx(expected, abs=1e-4)


async def test_prediction_is_persisted_and_queryable(session, small_bar_settings):
    model_id, version = await _seed_and_train(session, small_bar_settings)
    await predict_latest(
        session, model_id=model_id, version=version, models_root=small_bar_settings.paths.root
    )

    rows = (
        await session.execute(
            select(ModelPrediction).where(ModelPrediction.model_version == version)
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_re_predicting_the_same_bar_upserts_not_duplicates(session, small_bar_settings):
    model_id, version = await _seed_and_train(session, small_bar_settings)
    await predict_latest(
        session, model_id=model_id, version=version, models_root=small_bar_settings.paths.root
    )
    await predict_latest(
        session, model_id=model_id, version=version, models_root=small_bar_settings.paths.root
    )

    rows = (
        await session.execute(
            select(ModelPrediction).where(ModelPrediction.model_version == version)
        )
    ).scalars().all()
    assert len(rows) == 1
