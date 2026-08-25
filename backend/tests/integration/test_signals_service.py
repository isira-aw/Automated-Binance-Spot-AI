"""Signal fusion orchestration against a real database (§30, §79, §80).

Marked ``integration``: requires a reachable PostgreSQL, skipped otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app.ml.training import run_training_job
from app.models.enums import SignalAction, SignalComponentKind
from app.models.market import Candle, TechnicalFeature
from app.models.ml import ModelPrediction, ModelVersion, TrainingRun
from app.models.trading import Signal, SignalComponent
from app.signals.service import generate_signal
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


async def _truncate(session) -> None:
    """Clean before and after: cleaning only afterwards makes a test depend on
    the database starting empty, which fails spuriously against existing data.
    """
    for table in (
        SignalComponent,
        Signal,
        ModelPrediction,
        TrainingRun,
        ModelVersion,
        TechnicalFeature,
        Candle,
    ):
        await session.execute(table.__table__.delete())
    await session.commit()


@pytest.fixture
async def session(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await _truncate(session)
        yield session
        await session.rollback()
        await _truncate(session)


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


async def _seed_candles_and_features(session, settings, *, count: int = 300) -> None:
    rng = np.random.default_rng(1)
    start = datetime(2024, 1, 1, tzinfo=UTC)
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
    await compute_and_store_all(
        session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version=settings.models.feature_version
    )


async def test_no_technical_features_yields_no_signal(session, small_bar_settings):
    result = await generate_signal(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )
    assert result is None

    rows = (await session.execute(select(Signal))).scalars().all()
    assert rows == []


async def test_technical_only_fusion_when_no_model_is_registered(session, small_bar_settings):
    await _seed_candles_and_features(session, small_bar_settings)

    signal = await generate_signal(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )
    assert signal is not None
    assert signal.action in {a.value for a in SignalAction}

    kinds = {c.kind: c for c in signal.components}
    assert kinds[SignalComponentKind.TECHNICAL.value].active is True
    assert kinds[SignalComponentKind.LIGHTGBM.value].active is False


async def test_signal_and_components_are_persisted(session, small_bar_settings):
    await _seed_candles_and_features(session, small_bar_settings)
    signal = await generate_signal(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )

    stored = (
        await session.execute(select(Signal).where(Signal.id == signal.id))
    ).scalar_one()
    assert stored.symbol == SYMBOL
    assert stored.timeframe == TIMEFRAME
    assert stored.venue == "PAPER"

    components = (
        await session.execute(
            select(SignalComponent).where(SignalComponent.signal_id == signal.id)
        )
    ).scalars().all()
    assert {c.kind for c in components} == {
        SignalComponentKind.TECHNICAL.value,
        SignalComponentKind.LIGHTGBM.value,
    }


async def test_regenerating_the_same_bar_upserts_not_duplicates(session, small_bar_settings):
    await _seed_candles_and_features(session, small_bar_settings)
    first = await generate_signal(session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME)
    second = await generate_signal(session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME)

    assert first.id == second.id
    rows = (await session.execute(select(Signal))).scalars().all()
    assert len(rows) == 1

    components = (
        await session.execute(
            select(SignalComponent).where(SignalComponent.signal_id == first.id)
        )
    ).scalars().all()
    assert len(components) == 2


async def test_fusion_with_a_registered_lightgbm_model(session, small_bar_settings):
    await _seed_candles_and_features(session, small_bar_settings, count=400)
    outcome = await run_training_job(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )
    assert outcome.model_version is not None

    signal = await generate_signal(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )
    assert signal is not None

    kinds = {c.kind: c for c in signal.components}
    assert kinds[SignalComponentKind.TECHNICAL.value].active is True
    assert kinds[SignalComponentKind.LIGHTGBM.value].active is True
    assert kinds[SignalComponentKind.LIGHTGBM.value].version == outcome.model_version


async def test_reason_codes_are_recorded_for_audit(session, small_bar_settings):
    await _seed_candles_and_features(session, small_bar_settings)
    signal = await generate_signal(
        session, small_bar_settings, symbol=SYMBOL, timeframe=TIMEFRAME
    )
    assert isinstance(signal.reason_codes, list)
    assert len(signal.reason_codes) > 0
