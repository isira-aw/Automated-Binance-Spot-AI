# Trading modes

```
BACKTEST  →  PAPER  →  BINANCE TESTNET  →  LIVE (explicitly armed)
```

| Mode | Data | Orders | Money |
| --- | --- | --- | --- |
| `BACKTEST` | Stored history | Simulated over historical candles | None |
| `PAPER` | Live market data | Internal simulator: fees, slippage, latency, partial fills | None |
| `BINANCE_TESTNET` | Binance testnet | Real order flow against the testnet | None |
| `LIVE` | Binance production | Real orders | **Real funds** |

`PAPER` is the primary Tier 1 development and validation mode.

## Live trading safety

- `LIVE_TRADING_ENABLED=false` by default.
- `TRADING_MODE=LIVE` with the flag unset is a **startup failure**, not a
  warning — the backend refuses to start.
- The UI requires an explicit `ARM LIVE TRADING` confirmation on top of the
  environment flag.
- After a restart, `LIVE` is never restored implicitly: the persisted mode is
  downgraded to `PAPER` unless both the arm flag and the environment flag are
  set.
- Emergency stop halts new entries immediately. What happens to *existing*
  positions is configurable — there is never a silent blanket market-sell
  unless that behaviour has been configured deliberately.

## Small account handling

The target account is under $50. Most signals are expected to be rejected with
`TRADE_NOT_ECONOMIC` because the position would fall below Binance's minimum
notional or because fees would consume the expected edge. That is the correct
outcome. The UI states the reason, the estimated fees and slippage, and the
recommended minimum capital, rather than hiding the rejection.
