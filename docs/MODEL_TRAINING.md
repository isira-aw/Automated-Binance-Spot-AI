# Model training

> **Status: not implemented.** The registry schema, artifact integrity checks
> and versioning rules exist; LightGBM training is Tier 1 phase 9.

## Pipeline

```
DATA → VALIDATION → FEATURE ENGINEERING → TRAIN → VALIDATION → BACKTEST →
OUT-OF-SAMPLE TEST → PAPER VALIDATION → MODEL REGISTRY
```

## What models predict

`P(up) / P(neutral) / P(down)` — never a raw price. Class probabilities are
mapped onto the unified `[0, 1]` fusion scale by one central, versioned
function, so no component invents its own scale.

## Registry

States: `CANDIDATE → VALIDATED → PRODUCTION → ARCHIVED`, plus `REJECTED`.
Previous production models are never auto-deleted; their artifacts and metadata
are kept so a rollback is always possible.

Artifacts are never overwritten:

```
models/production/current/
models/candidates/model_<version>/
models/archive/model_<version>/
```

Metadata lives in PostgreSQL (`model_versions`), and every row records its
artifact path and SHA-256. Startup verifies both.

## Feature versioning

Every trained model records a `feature_version`. Running a model against
incompatible features is a hard error, not a warning.

## Promotion

Trading metrics decide promotion — net return, Sharpe, Sortino, drawdown,
profit factor, expectancy, turnover, fees, slippage, win rate. ML metrics
(accuracy, precision/recall, ROC-AUC, Brier score, calibration) are diagnostic
only. High raw prediction accuracy never qualifies a model on its own.

Probabilistic outputs are calibration-tested: a stated 0.70 confidence must
correspond to roughly a 70% empirical outcome frequency over the evaluation
window. Raw neural-network confidence is never trusted without that check.

A candidate that is worse than production is `REJECT`ed. Production is never
replaced without validation.
