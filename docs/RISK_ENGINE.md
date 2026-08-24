# Risk engine

> **Status: not implemented.** The risk *parameters* and their authority model
> are defined and exposed; the engine that evaluates them is Tier 1 phase 10.

## Authority model

The risk engine is the highest-authority component in the system. No ML model,
no LLM, no strategy configuration and no frontend request may bypass it. Every
order will flow through:

```
Signal → Risk Engine → Order Validator → Exchange Rules Validator → Execution
```

An order is never placed directly from a model prediction.

## Parameters — single source of truth

Defined once in `backend/app/config/risk_config.py` and referenced everywhere
else. Fractions are decimals in `[0, 1]`.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `max_risk_per_trade` | 0.01 | Fraction of equity risked on one trade |
| `max_position_size` | 0.35 | Max fraction of equity in one position |
| `max_asset_exposure` | 0.50 | Max fraction of equity exposed to one asset |
| `max_portfolio_exposure` | 0.80 | Max fraction of equity deployed overall |
| `max_simultaneous_positions` | 1 | Concurrent open positions |
| `max_daily_loss` | 0.03 | Daily loss fraction that pauses trading |
| `max_drawdown` | 0.15 | Peak-to-trough drawdown that pauses trading |
| `max_consecutive_losses` | 4 | Losing trades before a cooldown |
| `max_slippage` | 0.002 | Max tolerated slippage vs. signal price |
| `spread_protection` | 0.001 | Max tolerated bid/ask spread fraction |
| `volatility_protection` | 0.08 | Max tolerated ATR/price ratio |
| `stale_data_protection_seconds` | 120 | Data older than this is never traded on |
| `api_failure_protection_threshold` | 5 | Consecutive API failures before pausing |
| `model_health_protection` | true | Block trading when the model is unhealthy |
| `cooldown_period_seconds` | 900 | Minimum wait after an exit, per symbol |

`RiskConfig` is frozen and rejects unknown fields, so a limit cannot be mutated
at runtime or silently redefined under a new name.

`max_simultaneous_positions` defaults to 1 deliberately: at an account size
under $50, concentrating in the single best opportunity beats spreading fees
across three positions.

## Decisions

The engine will return `APPROVED | REJECTED | PAUSED` with a human-readable
explanation, surfaced to the frontend as, for example:

```
Trade rejected
Reason: Maximum daily loss reached
No order was submitted.
```

Every decision is persisted to `risk_events`, whether or not it blocked a trade.

## What the engine will never do

- Increase risk after a loss. There is no martingale, ever.
- Force an order that is below the exchange minimum. Undersized trades are
  rejected as `TRADE_NOT_ECONOMIC` — the expected common outcome at this
  account size, not an edge case to suppress.
- Trade on stale market data, or on a model that reports unhealthy.
- Be overridden by an LLM. Claude and Ollama are analysis components only.
