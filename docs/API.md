# API

Base path: `/api/v1`. Interactive docs at `/docs` (development only).

## Implemented endpoints

| Method | Path                   | Description                                     |
| ------ | ---------------------- | ----------------------------------------------- |
| GET    | `/system/health`       | Component health; 503 when something is unhealthy |
| GET    | `/system/ping`         | Cheap liveness probe (used by the container health check) |
| GET    | `/system/version`      | App, environment, strategy/feature version, schema revision |
| GET    | `/system/state`        | Persisted mode, engine state, model registry integrity |
| GET    | `/system/tiers`        | Which components exist and which influence decisions |
| GET    | `/settings`            | Effective non-secret configuration               |
| GET    | `/settings/risk`       | The authoritative risk limits                    |
| WS     | `/ws`                  | Structured event stream                          |

## Registered but not implemented

These namespaces exist so the contract is stable, and every one returns
HTTP 501 with `code: "NOT_IMPLEMENTED"` until its engine is built:

`/market` `/signals` `/orders` `/positions` `/trades` `/risk` `/backtests`
`/paper-trading` `/binance` `/models` `/training` `/patterns` `/news`
`/fundamentals`

## Error format

Every error uses one envelope:

```json
{
  "error": {
    "code": "RISK_LIMIT_EXCEEDED",
    "message": "Daily loss limit has been reached",
    "metadata": null
  }
}
```

Known codes: `NOT_FOUND`, `VALIDATION_ERROR`, `CONFIGURATION_ERROR`,
`SERVICE_UNAVAILABLE`, `RISK_LIMIT_EXCEEDED`, `TRADING_DISABLED`,
`NOT_IMPLEMENTED`, `INTERNAL_ERROR`.

Every response carries an `x-request-id` header, echoing the client's if one was
supplied; the same id appears in the structured logs.

## WebSocket

Connect to `/api/v1/ws`. Every message uses the envelope:

```json
{ "event": "signal_created", "timestamp": "2026-08-24T12:00:00+00:00", "data": {} }
```

### Event types

| Group    | Events                                                                    |
| -------- | ------------------------------------------------------------------------- |
| Market   | `market_update`, `ticker_update`, `candle_closed`                          |
| Signals  | `signal_created`, `signal_updated`                                         |
| Trading  | `order_created`, `order_updated`, `order_filled`, `position_updated`, `portfolio_updated` |
| Risk     | `risk_event`                                                               |
| Models   | `model_status`, `training_status`, `backtest_status`                       |
| Tier 2   | `news_update`                                                              |
| System   | `system_status`, `log_event`                                               |
| Transport| `heartbeat`, `subscription_updated`, `error`                               |

Only `system_status`, `heartbeat`, `subscription_updated`, `log_event` and
`error` are emitted today — the rest arrive with their engines. None of them is
ever emitted with fabricated data.

### Client messages

```json
{"action": "subscribe",   "events": ["risk_event", "signal_created"]}
{"action": "unsubscribe", "events": ["log_event"]}
{"action": "pong"}
```

A client that never subscribes receives every event. The server sends a
`heartbeat` on an interval and closes connections that stop responding. The
frontend client reconnects with exponential backoff (500 ms → 15 s).
