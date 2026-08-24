# Project status

Last updated: 2026-08-24 · Track: **MVP / Tier 1** · Phase 6 of 20

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

**Phase 5 — Binance market-data connector**
- `BinanceService` over a REST client, WebSocket stream client, market-data
  service and exchange-metadata cache. Read-only: the package contains no
  order-placing surface, and no withdrawal endpoint exists anywhere (§70) —
  both are asserted by tests, not just by convention.
- Rate limits are read from live `exchangeInfo` and enforced by a weighted
  sliding window per declared rule. No limit value is hard-coded; the
  configured fallbacks apply only until the first response arrives (§71).
- Server-time synchronisation measured against the request midpoint, so
  latency contributes at most half the round trip. A `-1021` rejection forces
  a re-sync and one retry rather than widening `recvWindow` (§72).
- Error taxonomy separating transport, rate-limit, server, request, timestamp
  and auth failures, each with an explicit retryable/not-retryable rule.
  Auth errors never echo the signature or secret.
- `candle_closed` is published only when the exchange's own closed flag is set,
  and `closed_klines()` drops the in-progress bar — the §16/§18 guard against
  an open candle reaching feature building.
- Deterministic mock connector (`app/binance/mock.py`); no test touches the
  network or uses real credentials (§62, §63).
- `binance` and `market_data` health probes replace their `NOT_IMPLEMENTED`
  placeholders. A stale stream reports DEGRADED with trading blocked, and a
  stream that has never delivered counts as stale.
- An unreachable exchange degrades startup instead of stopping it (§44).

**Phase 6 — historical data ingestion**
- `backfill_symbol_timeframe` pages through `klines` from wherever a
  symbol/timeframe last left off (`market_data_metadata.last_candle_open`),
  defaulting to a pre-Binance epoch on a first run — each asset's history is
  independent (§17). A run bounded by `max_pages` resumes cleanly next time
  rather than restarting from scratch.
- Only closed candles are ever persisted, via a Postgres `ON CONFLICT DO
  UPDATE` upsert on the natural key — re-ingesting the same page updates in
  place rather than duplicating rows.
- `market_data_metadata` (coverage) is updated per committed page, not only
  at the end, so an interrupted run leaves accurate progress behind.
- Integrity validation (`validate_symbol_timeframe`) checks duplicate
  timestamps, UTC boundary alignment, OHLC consistency, non-positive values
  and gaps, and persists the report to `market_data_metadata` rather than
  only logging it. A gap or an unusually large move is recorded but does not
  by itself mark the data "dirty" — only structural corruption does.
- `market` API: `GET /coverage`, `GET /candles` (reads from Postgres, never
  live from Binance), `POST /backfill` (backgrounded, pollable via
  `GET /backfill/status`), `POST /integrity/validate`. A whole-job failure
  (e.g. the database becomes unreachable mid-run) is captured on the job
  rather than disappearing silently.
- Frontend Data page: real coverage table, backfill trigger, and integrity
  check, wired to the endpoints above — no synthetic data anywhere (§96).

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
| Backend unit | 158 | pass |
| Backend API + WebSocket integration | 34 | pass |
| Backend database integration | 18 | pass (real PostgreSQL 16); skip without one |
| Frontend (vitest) | 12 | pass |

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
- The Binance layer has never been exercised against the live exchange from
  this environment: every test runs against the deterministic mock or a
  scripted HTTP transport. Request/response shapes follow the current public
  documentation, but the first real handshake happens on the target machine,
  and `/system/health` is where a mismatch will show.
- A real backfill against live Binance history has not been run — a mock
  bug (it ignored `startTime`, always returning the most recent page) was
  caught by the ingestion tests and fixed, but the actual data volume and
  timing of a multi-year, multi-symbol backfill against live rate limits is
  unverified. `POST /market/backfill` is bounded per call (`max_pages`,
  default 200) and resumable, so an unexpectedly large history is a slow
  fix, not a stuck one.
- `POSTGRES_PASSWORD` is fixed when PostgreSQL first initialises its data
  directory; changing it in `.env` afterwards causes an authentication failure
  until the server password is changed to match (see TROUBLESHOOTING.md).

## Next phase

**Phase 7 — technical analysis engine.**

1. Trend, momentum, volatility and volume indicators (§19) computed from the
   persisted closed candles, versioned as `feature_version`.
2. Persist to `technical_features`; never recompute a feature from an
   incomplete or still-open candle (§16, §18 continue to apply).
3. Multi-timeframe feature alignment per the 1D/4H/1H/15M rules (§16).

Then Phase 8 (market structure) and Phase 9 (LightGBM baseline).
