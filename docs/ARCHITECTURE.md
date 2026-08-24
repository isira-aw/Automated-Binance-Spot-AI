# Architecture

## Shape of the system

```
React + Vite (browser)
        │  REST /api/v1/*        WebSocket /api/v1/ws
        ▼
FastAPI backend  ──►  PostgreSQL   (persistent source of truth)
        │        ──►  Redis        (hot state, cache)
        │
        └──►  Binance Spot REST + WebSocket   [not built yet]
```

The browser never touches PostgreSQL, Redis, Binance credentials, model files,
or the filesystem. Everything goes through the backend.

## Backend module map

```
backend/app/
  api/            FastAPI routers, middleware, application factory
  config/         structured settings; risk_config.py is the risk source of truth
  core/           errors, structured logging, event contract, UTC time helpers
  database/       engine/session management, Redis client, declarative base
  models/         SQLAlchemy ORM models (one module per domain area)
  migrations/     Alembic environment and versions
  monitoring/     component health aggregation, log-to-WebSocket bridge
  schemas/        Pydantic request/response models
  services/       application services (persisted state, …)
  websocket/      event bus and connection manager
  ml/             model registry integrity; models land here in later phases
  binance/ technical/ patterns/ risk/ trading/ paper_trading/ backtesting/
  news/ llm/ engines/ workers/ utils/       — reserved for later phases
  lifespan.py     startup/shutdown sequence
  main.py         ASGI entrypoint only; no business logic
```

## Configuration

`app/config/settings.py` builds one nested `Settings` object from environment
variables and `.env`. Risk parameters live *only* in
`app/config/risk_config.py` — every other layer references that model rather
than restating limits, so definitions cannot drift apart.

`RiskConfig` is frozen and rejects unknown fields, which makes an accidental
redefinition (a new limit name, a mutated limit at runtime) a hard error.

## Startup sequence

1. Validate configuration — production may not run with wildcard CORS, and
   `TRADING_MODE=LIVE` without `LIVE_TRADING_ENABLED=true` refuses to start.
2. Ensure the persistent directory layout exists.
3. Initialise the event bus and WebSocket connection manager.
4. Connect PostgreSQL; verify migrations have been applied.
5. Connect Redis.
6. Verify every registered model artifact exists on disk; demote any PRODUCTION
   model whose artifact is missing or has a mismatched checksum.
7. Load persisted application state — LIVE is never restored implicitly.
8. Register health probes.

Dependency failures do not crash the process: they are recorded and surfaced
through `GET /api/v1/system/health`, which returns HTTP 503 when a component
that is expected to be running is not.

## Event flow

Publishers never hold a socket. They publish an `Event` onto the in-process
event bus; the connection manager fans it out to subscribers. Every subscriber
queue is bounded — a stalled browser drops its own oldest events instead of
growing backend memory.

```python
Event.of(EventType.RISK_EVENT, rule="max_daily_loss", decision="REJECTED")
# → {"event": "risk_event", "timestamp": "...", "data": {...}}
```

## Data integrity rules baked into the core

- Every timestamp is timezone-aware UTC. Laptop local time is never used for
  candle-boundary logic.
- A candle may only be used as a feature input once it has fully closed at its
  own timeframe boundary. `app/core/time_utils.py` implements this; a lower
  timeframe may close inside a still-open parent, never the reverse.
- Log records are scrubbed of anything key-shaped before reaching a handler.

## Tiering

Tier 1 (core) is everything needed to trade on technical analysis plus a
LightGBM baseline. Tier 2 (Transformer, ensemble, news, Ollama, Claude,
patterns, regimes) is optional and disabled by default; Tier 1 must keep
operating with all of it switched off. `GET /api/v1/system/tiers` reports which
components exist and which actually influence decisions, so the UI can label
shadow/research surfaces honestly.
