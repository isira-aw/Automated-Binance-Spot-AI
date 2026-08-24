# Project status

Last updated: 2026-08-24 · Track: **MVP / Tier 1** · Phase 1 of 20

**Phase 1 is verified running on real infrastructure.** `docker compose up -d`
brings up postgres, redis, backend and frontend; migrations apply
(`0001_initial_schema`, 31 tables); `/api/v1/system/health` reports
`overall: ONLINE` with every unbuilt component explicitly `NOT_IMPLEMENTED`
and every Tier 2 component `DISABLED`.

## Completed

**Phase 1 — repository structure, Docker, configuration**
- Directory layout for backend, frontend, persistent storage, docs and scripts.
- `docker-compose.yml` (postgres, redis, migrate, backend, frontend) with health
  checks; dependent services wait on health, never on `sleep`. Dev overlay adds
  backend hot reload and the Vite dev server.
- Structured configuration (`app/config`) with nested Pydantic settings.
  Risk parameters defined once, frozen, in `app/config/risk_config.py`.
- Environment separation with safe defaults; production refuses wildcard CORS,
  and `TRADING_MODE=LIVE` without `LIVE_TRADING_ENABLED=true` refuses to start.
- `.env.example` with placeholders only; `.env`, `data/`, `models/`,
  `artifacts/`, `logs/`, `backups/`, `secrets/` gitignored.

**Phase 2 — PostgreSQL, migrations, persistent storage**
- All 30 tables from the specification, as SQLAlchemy models across
  `models/{system,market,news,ml,trading,backtesting}.py`.
- Alembic wired to application settings (no credentials in `alembic.ini`);
  initial migration `0001_initial_schema`. The schema is never created
  implicitly at startup.
- Persistent bind mounts survive `docker compose down`.
- Model-registry artifact integrity check: a registry row whose artifact is
  missing or checksum-mismatched cannot remain `PRODUCTION`.

**Phase 3 — FastAPI REST architecture**
- Application factory; `main.py` holds no business logic.
- Request-id middleware, structured JSON logging with secret redaction and
  rotation, single error envelope for every failure path.
- Implemented: `/system/health`, `/system/ping`, `/system/version`,
  `/system/state`, `/system/tiers`, `/settings`, `/settings/risk`.
- All remaining namespaces registered and returning 501 `NOT_IMPLEMENTED`.

**Phase 4 — WebSocket architecture**
- Bounded-queue event bus with backpressure that drops a slow client's oldest
  events rather than growing memory.
- Connection manager: heartbeats, stale-connection detection, subscription
  management, graceful disconnect, connection cap.
- Log-to-WebSocket bridge for the live log viewer.

**Phase 14/15 (partial) — frontend core shell**
- React + Vite + TypeScript + Tailwind dark dashboard shell with all 17 routes.
- Implemented pages: Dashboard, System, Settings, Logs.
- REST client with typed errors; WebSocket client with exponential-backoff
  reconnect and heartbeat replies.
- Tier labelling: the UI reports which components influence decisions (today:
  none) rather than implying Tier 2 surfaces are live.

**Phase 18 (partial) — migration tooling**
- `scripts/manage.py` (backup, restore, export, import, migrate, verify) with
  Makefile and PowerShell wrappers.

## In progress

Nothing. Phase 1 is complete and the stack is in a working state.

## Blocked

Nothing.

## Tests

| Suite | Count | Result |
| --- | --- | --- |
| Backend unit | 46 | pass |
| Backend API + WebSocket integration | 23 | pass |
| Backend database integration | 5 | skipped without PostgreSQL |
| Frontend (vitest) | 10 | pass |

Lint: `ruff` clean, `eslint --max-warnings 0` clean, `tsc --noEmit` clean.

Coverage highlights: UTC candle-closure rules, risk-config immutability and
range validation, live-trading defaults, CORS policy, event-bus backpressure,
log secret redaction, health aggregation semantics (including that unbuilt and
disabled components never mark the system unhealthy), registry integrity,
the full REST contract, and the WebSocket protocol.

## Known issues and limitations

- **No trading functionality exists.** No market data, no signals, no orders.
  This is expected at Phase 1 and is stated explicitly in the UI and API rather
  than masked with placeholder data.
- Settings are read-only in the UI; the configuration write API arrives with the
  trading engine.
- Background workers and the scheduler have no services in `docker-compose.yml`
  yet — they are added when there is work for them to do.
- Docker images cannot be built in the development session (no Docker daemon);
  the stack is verified by running it on the target machine instead. Five
  defects reached that machine because local checks never exercised a real
  container or a real `.env`: the ORM package excluded from the image by an
  unanchored gitignore rule, flat environment variables ignored by nested
  settings sections, comma-separated list values rejected by the env source,
  CRLF line endings from Windows, and healthchecks resolving `localhost` to
  IPv6. There is still no CI running a clean checkout, so this class of bug is
  caught only by running the stack.
- The database integration tests need a running PostgreSQL with migrations
  applied; they skip themselves otherwise. The initial migration has now been
  applied against a real PostgreSQL 16 as well as in the deployed stack.
- `POSTGRES_PASSWORD` is fixed when PostgreSQL first initialises its data
  directory; changing it in `.env` afterwards causes an authentication failure
  until the server password is changed to match (see TROUBLESHOOTING.md).

## Next phase

**Phase 5 — Binance market-data connector.**

1. `BinanceService` with REST and WebSocket clients, exchange metadata and
   symbol-filter retrieval.
2. Rate limits read from live `exchangeInfo`, kept configurable — no
   hard-coded remembered limit values.
3. Server-time synchronisation and explicit `recvWindow` error handling.
4. A mock connector for automated tests; real credentials never used in tests.
5. Ticker and kline streams publishing `ticker_update` and `candle_closed`,
   with `candle_closed` gated on the exchange's own closed flag.
6. `binance` and `market_data` health probes replacing their `NOT_IMPLEMENTED`
   placeholders.

Then Phase 6 (historical ingestion with integrity validation) and Phase 7
(technical analysis engine).
