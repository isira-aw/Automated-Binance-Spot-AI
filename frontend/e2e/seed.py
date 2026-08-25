"""Seeds the data the Phase 17 frontend E2E suite drives the UI against.

Run with the *backend's* virtualenv and working directory, since it imports
the backend package directly to reuse the exact same feature computation and
training code the rest of the system uses -- not a second, drifting copy of
that logic:

    cd backend
    POSTGRES_HOST=localhost POSTGRES_PORT=5432 PYTHONPATH=. .venv/bin/python \
        ../frontend/e2e/seed.py

Truncates and reseeds a deterministic BTCUSDT/1h uptrend, computes technical
features, and trains a LightGBM baseline -- the same "candles in, a
generated signal's LightGBM leg active" state
``tests/integration/test_e2e_signal_to_trade.py`` seeds on the backend side,
so the two suites are exercising the same scenario from two directions.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.ml.training import run_training_job
from app.models.market import Candle, TechnicalFeature
from app.models.ml import ModelPrediction, ModelVersion, TrainingRun
from app.models.trading import (
    PaperOrder,
    PaperPosition,
    PortfolioSnapshot,
    RiskEvent,
    Signal,
    SignalComponent,
    Trade,
)
from app.technical.feature_engine import compute_and_store_all

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"


async def main() -> None:
    settings = Settings(
        _env_file=None,
        models={
            "feature_version": "v1",
            "label_horizon": 3,
            "label_threshold": 0.001,
            "min_training_rows": 50,
            "min_validation_accuracy": 0.0,
            "min_validation_macro_f1": 0.0,
        },
    )
    engine = create_async_engine(settings.database.async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        for table in (
            PaperOrder,
            PaperPosition,
            Trade,
            PortfolioSnapshot,
            RiskEvent,
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

        rng = np.random.default_rng(1)
        start = datetime(2024, 1, 1, tzinfo=UTC)
        count = 400
        trend = np.cumsum(rng.choice([1.0, -1.0], size=count, p=[0.7, 0.3])) * 0.5
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
            session, symbol=SYMBOL, timeframe=TIMEFRAME, feature_version="v1"
        )
        outcome = await run_training_job(session, settings, symbol=SYMBOL, timeframe=TIMEFRAME)
        print(f"Seeded {count} candles for {SYMBOL}/{TIMEFRAME}.")
        print(f"Trained model version: {outcome.model_version} ({outcome.registry_status})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
