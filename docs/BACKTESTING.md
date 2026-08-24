# Backtesting

> **Status: not implemented.** The `backtest_runs` and `backtest_trades` tables
> and the run/assumption schema exist; the engine is Tier 1 phase 12.

## Design commitments

- **Event-driven**, simulating market data, signal generation, model
  predictions, risk evaluation, order execution, fees, slippage, position
  sizing, stop-loss/take-profit/trailing, and portfolio accounting.
- **Same components as live.** The backtester reuses the same strategy and risk
  code that paper and live trading use. A backtest-only strategy variant is a
  bug, not a shortcut.
- **Never uses future data.** See the audit below.
- **Never zero-cost.** Maker fee, taker fee, slippage and spread are always
  applied, from the configured Binance fee assumptions.

## Mandatory look-ahead audit

Before a backtest result is treated as meaningful, the run records explicit
answers to:

- future feature leakage
- future normalisation statistics
- future news
- survivorship bias
- unrealistic fills
- zero slippage / zero fees
- impossible liquidity
- impossible order execution

These are stored in `backtest_runs.assumptions` and printed in every report. A
run without them is not a result.

## Reproducibility

Every run records `strategy_version`, `model_version`, `feature_version`, the
data range, fees, slippage and initial capital, so a result can be reproduced
from its inputs.

## Validation method

Walk-forward only: `TRAIN → VALIDATE → TEST`, then roll forward. Random
train/test splits are never used on temporal data. Every experiment — including
rejected ones — is logged to `training_runs`, which is what makes repeated
optimisation visible after the fact.
