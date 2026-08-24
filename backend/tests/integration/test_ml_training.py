"""LightGBM training pipeline end-to-end against a real database (§24, §37, §39).

Marked ``integration``: requires a reachable PostgreSQL with migrations
applied, skipped automatically otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app.ml.training import run_training_job
from app.models.enums import JobStatus, ModelStatus
from app.models.market import Candle
from app.models.ml import ModelVersion, TrainingRun
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
        for table in (TrainingRun, ModelVersion):
            await session.execute(table.__table__.delete())
        from app.models.market import TechnicalFeature

        await session.execute(TechnicalFeature.__table__.delete())
        await session.execute(Candle.__table__.delete())
        await session.commit()


async def _seed_learnable_history(session, *, count: int, seed: int = 0) -> None:
    """Candles with a real, learnable structure: momentum persists, so a
    model that has learned anything at all should beat chance on direction.
    Not a claim this is a good trading signal -- just enough signal that a
    correctly-wired pipeline visibly learns something (mirrors the approach
    in test_lightgbm_model.py's learnable_dataset)."""
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=UTC)

    trend = np.cumsum(rng.choice([1.0, -1.0], size=count, p=[0.6, 0.4])) * 0.5
    noise = rng.normal(0, 0.3, count)
    close = 100 + trend + noise

    session.add_all(
        [
            Candle(
                symbol=SYMBOL,
                timeframe=TIMEFRAME,
                open_time=start + timedelta(hours=i),
                close_time=start + timedelta(hours=i + 1),
                open=float(close[i]),
                high=float(close[i] + abs(rng.normal(0, 0.1))),
                low=float(close[i] - abs(rng.normal(0, 0.1))),
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


@pytest.fixture
def small_bar_settings():
    return make_settings(
        models={
            "feature_version": "v1",
            "label_horizon": 3,
            "label_threshold": 0.001,
            "train_fraction": 0.7,
            "validation_fraction": 0.15,
            "min_training_rows": 50,
            "min_validation_accuracy": 0.0,  # accept anything for the "always registers" tests
            "min_validation_macro_f1": 0.0,
        }
    )


async def test_training_job_is_recorded_even_before_it_can_succeed(session, small_bar_settings):
    """No candles at all -- must still leave an auditable record (§22, §36),
    never just silently do nothing."""
    outcome = await run_training_job(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )
    assert outcome.status is JobStatus.FAILED
    assert outcome.error is not None

    run = (
        await session.execute(select(TrainingRun).where(TrainingRun.job_id == outcome.job_id))
    ).scalar_one()
    assert run.status == JobStatus.FAILED.value
    assert run.finished_at is not None
    assert run.error is not None


async def test_successful_training_registers_a_model_version(session, small_bar_settings, tmp_path):
    small_bar_settings.paths.models.mkdir(parents=True, exist_ok=True)
    await _seed_learnable_history(session, count=300)
    await compute_and_store_all(session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version="v1")

    outcome = await run_training_job(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )
    assert outcome.status is JobStatus.SUCCEEDED
    assert outcome.model_version is not None

    registry_row = (
        await session.execute(
            select(ModelVersion).where(ModelVersion.version == outcome.model_version)
        )
    ).scalar_one()
    assert registry_row.model_type == "LIGHTGBM"
    assert registry_row.symbol == SYMBOL
    assert registry_row.timeframe == TIMEFRAME
    assert registry_row.feature_version == "v1"
    assert registry_row.status in {ModelStatus.CANDIDATE.value, ModelStatus.VALIDATED.value}


async def test_artifact_is_written_to_disk_and_matches_its_checksum(
    session, small_bar_settings
):
    await _seed_learnable_history(session, count=300)
    await compute_and_store_all(session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version="v1")
    outcome = await run_training_job(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )

    registry_row = (
        await session.execute(
            select(ModelVersion).where(ModelVersion.version == outcome.model_version)
        )
    ).scalar_one()

    import hashlib

    artifact_path = small_bar_settings.paths.root / registry_row.artifact_path
    assert artifact_path.is_file()
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert digest == registry_row.artifact_sha256


async def test_metrics_are_recorded_for_both_validation_and_test_splits(
    session, small_bar_settings
):
    await _seed_learnable_history(session, count=300)
    await compute_and_store_all(session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version="v1")
    outcome = await run_training_job(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )

    registry_row = (
        await session.execute(
            select(ModelVersion).where(ModelVersion.version == outcome.model_version)
        )
    ).scalar_one()
    assert "validation" in registry_row.metrics
    assert "test" in registry_row.metrics
    assert "accuracy" in registry_row.metrics["validation"]


async def test_low_accuracy_candidate_is_kept_not_deleted(session):
    """§39: a candidate that fails the bar still exists in the registry,
    status CANDIDATE, with an explanatory note -- it is never dropped."""
    strict_settings = make_settings(
        models={
            "feature_version": "v1",
            "label_horizon": 3,
            "label_threshold": 0.001,
            "min_training_rows": 50,
            "min_validation_accuracy": 0.999,  # impossible to clear
            "min_validation_macro_f1": 0.999,
        }
    )
    await _seed_learnable_history(session, count=300)
    await compute_and_store_all(session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version="v1")
    outcome = await run_training_job(session, strict_settings, symbol=SYMBOL, timeframe=TIMEFRAME)

    assert outcome.status is JobStatus.SUCCEEDED  # training itself succeeded
    assert outcome.registry_status is ModelStatus.CANDIDATE  # but not promoted

    registry_row = (
        await session.execute(
            select(ModelVersion).where(ModelVersion.version == outcome.model_version)
        )
    ).scalar_one()
    assert registry_row.status == ModelStatus.CANDIDATE.value
    assert registry_row.notes is not None


async def test_two_training_runs_produce_two_distinct_versions(session, small_bar_settings):
    """Re-training must never silently overwrite a previous model version --
    every version is kept (§39, §77)."""
    await _seed_learnable_history(session, count=300)
    await compute_and_store_all(session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version="v1")

    first = await run_training_job(session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME)
    second = await run_training_job(session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME)

    assert first.model_version != second.model_version
    all_versions = (await session.execute(select(ModelVersion))).scalars().all()
    assert len(all_versions) == 2
