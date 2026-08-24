# Project status

Last updated: 2026-08-24 · Track: **MVP / Tier 1** · Phase 12 of 20

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

**Phase 7 — technical analysis engine**
- `app/technical/indicators.py`: every §19 category (trend, momentum,
  volatility, volume) as pure pandas functions over closed-candle OHLCV.
  Every function is causal by construction (rolling windows aligned to the
  current row, recursive EMA/Wilder smoothing, no centred windows or forward
  shifts) — checked directly by `test_indicators_no_lookahead.py`, which
  recomputes each indicator on a truncated prefix of a series and asserts the
  values match the full computation exactly. A negative control (a
  deliberately centred rolling window) proves the check would actually catch
  a leak, not just pass by construction.
- `feature_engine.py` persists one feature row per closed candle to
  `technical_features`, tagged with `feature_version` (§78); a windowed
  indicator not yet ready is stored as JSON `null`, never fabricated or
  silently dropped. `compute_latest` runs incrementally as new candles close;
  `compute_and_store_all` recomputes the whole stored history after a
  backfill.
- The market stream bridge now persists every closed candle it receives (not
  only backfilled history) and refreshes that symbol/timeframe's feature
  vector immediately — closing a gap from Phase 5/6 where live closed candles
  were published to WebSocket clients but never reached PostgreSQL, so
  features would have silently gone stale outside of manual re-backfills. A
  failure here degrades (logged, one candle's features delayed) rather than
  dropping the stream connection (§44).
- `market` API additions: `GET /features` (filtered to the active
  `feature_version`), `POST /features/compute`. The backfill job now computes
  features for whatever it just ingested.
- RSI's zero-division case (no losses in the window) was found by a unit test
  expecting the textbook value of exactly 100 and getting NaN instead; fixed
  to match the standard convention rather than silently dropping the
  strongest possible trend signal from the feature set.

**Phase 8 — market structure engine**
- `app/engines/market_structure.py`: HH/HL/LH/LL sequences, prevailing
  trend, Break of Structure, Change of Character, support/resistance levels,
  breakout/breakdown and false breakout (§20) — generated from price action
  alone, independent of any model.
- Swing points use a fractal-style window and are attributed to their
  *confirmation* bar (`index + window`), never their own bar: a swing high
  cannot be known until enough bars afterward have failed to exceed it. False
  breakouts go through the same delay a second time (does price revert within
  `FALSE_BREAKOUT_WINDOW` bars of the break). Getting this attribution wrong
  is a subtler form of the §18 leak than a centred window, so it gets the same
  truncated-prefix proof the indicator module uses, plus a deterministic
  negative control (a single hand-placed peak that is only detectable with
  enough trailing bars) — and separately, the actual production code was
  broken on purpose (attributing swings to their own bar) and confirmed the
  real no-lookahead test catches it before being restored.
- Structure fields are merged into the same `technical_features` JSONB row
  the indicator engine writes, tagged with the same `feature_version` —
  storage convenience only; the two are computed independently.

**Phase 9 — LightGBM baseline model**
- `app/ml/labeling.py`: three-class label (UP/NEUTRAL/DOWN) from the forward
  return over a configurable horizon, with a neutral band rather than forcing
  a direction on noise. Labels are deliberately forward-looking — that is
  the correct shape for a training target, not a §18 violation; nothing here
  feeds a label back in as a feature.
- `app/ml/dataset.py`: a single chronological TRAIN/VALIDATE/TEST split
  (§36 — never random on temporal data), with rows whose label window would
  reach across a split boundary dropped from the split on the earlier side of
  that boundary. This is the real leakage risk in a training pipeline (a
  label near a split edge "seeing" the next split's prices) and is proven
  directly: the last training row's forward-return window is checked to land
  strictly before the first validation row, with a negative control (the trim
  disabled) demonstrating the same check catches the leak when it's real.
- `app/ml/lightgbm_model.py`: the low-level `lgb.train`/`Booster` API rather
  than the sklearn wrapper, so class-probability order is fixed by the
  integer label encoding with no label-encoder object to keep in sync across
  a save/load round trip (§78, §80). The feature-column list is persisted
  alongside the model and re-asserted on load — a tampered or mismatched
  column list is a hard load-time error, not a silently misaligned matrix.
- `app/ml/metrics.py`: accuracy, macro F1, per-class precision/recall,
  log loss, multiclass Brier score (§85 calibration), and one-vs-rest
  macro ROC-AUC — reported as `null` with an explanatory note (not a
  fabricated number) when an evaluation window is missing a class (§84
  "where meaningful").
- `app/ml/prediction.py`: implements §30a's own documented fusion-score
  mapping (`P(up) - P(down)` rescaled to [0,1]) as the one central, versioned
  function every future signal-fusion adapter reuses. Every prediction is
  stored `shadow_mode=True` unconditionally — no risk engine, paper trading
  simulator or signal fusion exists yet to act on one, so nothing produced
  right now can influence a trade even in principle.
- `app/ml/training.py` orchestrates DATA → FEATURE ENGINEERING → TRAIN →
  VALIDATION → TEST → MODEL REGISTRY. The §37 steps this system cannot
  honestly perform yet (BACKTEST, PAPER VALIDATION, promotion to PRODUCTION)
  are explicitly left out rather than faked — a candidate can reach
  VALIDATED on ML metrics alone, never PRODUCTION, since §84 states trading
  metrics are the deciding factor for that and no backtest exists yet
  (Phase 12). Every run is recorded in `training_runs`, including failed
  ones (§22's p-hacking guard).
- `models` API un-pended: `GET /models`, `GET /models/{id}/{version}`,
  `POST /models/train` (backgrounded, pollable via `GET /models/train/status`,
  one job at a time — no benefit to contending for the same CPU cores on a
  laptop, §52), `POST /models/{id}/{version}/predict`.
- A real route-ordering bug was caught by the API tests: `GET /train/status`
  was being matched by the earlier `GET /{model_id}/{version}` pattern
  (both two path segments), so `/train/status` silently ran the registry-
  detail handler instead — fixed by registering literal-path routes before
  the dynamic ones.

**Phase 10 — risk engine**
- `app/risk/engine.py`: the highest-authority component (§31). Returns
  `APPROVED | REJECTED | PAUSED` with a human-readable reason the frontend
  surfaces verbatim (§101). Every limit is read from `RiskConfig` — this
  module enforces, it never redefines.
- Rule ordering is deliberate and tested: system health (emergency stop,
  stale data, API failures, model health) → account halts (daily loss,
  drawdown, loss streak) → per-trade checks (spread, volatility, slippage,
  cooldown, exposure, sizing). The first two produce `PAUSED`, the last
  `REJECTED`. Evaluating the other way round would let a per-trade rejection
  mask an account-level halt, reading to an operator as "that trade was bad"
  when the truth is "trading is stopped".
- `app/risk/position_sizing.py` (§32): sizes from equity, risk fraction, stop
  distance, fees and the live exchange filters from Phase 5. Rounds **down**
  onto the lot grid, never nearest, so a rounding artefact can only reduce
  risk below a cap and never nudge it above one. `TRADE_NOT_ECONOMIC` is a
  normal, expected answer at <$50 (§88), never suppressed or forced.
- Round-trip fees exceeding the amount risked reject the trade (§86): an
  edge smaller than its own transaction costs is not a trade.
- No martingale (§56) is enforced structurally, not by convention — risk is
  a constant fraction of equity, so a losing streak cannot size up; there is
  a test asserting exactly that.
- Authority is tested as a property: no `REJECTED`/`PAUSED` assessment ever
  carries a usable size, so a caller that ignores `decision` still cannot
  construct an order.
- `risk_events` records every rejection and pause (never approvals — those
  become orders, and duplicating one fact across two tables invites them to
  disagree), so "why didn't it trade?" is answerable after the fact.
- `risk` API un-pended, read-only by design: `GET /risk/parameters`,
  `GET /risk/state`, `GET /risk/events`. There is deliberately no endpoint
  that changes a limit — that is a Settings concern (§64).

**Phase 11 — internal paper trading simulator**
- Real market data, simulated execution: fills, fees, slippage, partial
  fills, balances, positions, P&L (§11B, §83).
- Split into pure, I/O-free modules (`fills.py`, `portfolio.py`,
  `simulator.py`) precisely so Phase 12 reuses them — §35 requires the
  backtest to share components with paper trading, and a backtest whose
  fills differ from paper trading's is not a backtest of this system.
- Slippage always moves against the trader; fees are always charged; there
  is no zero-cost path through the fill model (§87).
- Decimal throughout: float accumulation over thousands of fills drifts, and
  a drifting equity curve is a performance metric that lies.
- Win/loss is measured **net** of fees (§41). A symbol missing from the price
  map is valued at its entry price rather than dropped, so a data gap cannot
  show a phantom loss that trips the drawdown halt on its own.
- Every entry routes through the risk engine, and `open_position` re-validates
  the assessment rather than trusting its caller — the risk engine's authority
  has to hold even against a bug in the simulator itself.
- **A real intrabar-ordering bug was found and fixed**: the trailing stop was
  ratcheted from a bar's high, then that same bar's low was tested against the
  raised stop — silently assuming the high came first and handing the trade a
  better exit than OHLC can justify (§82). Exits now test against the stop as
  it stood entering the bar. The regression test carries a negative control:
  with the eager ratchet restored, the trade books a profit that never happened.

**Phase 12 — backtesting engine**
- Event-driven, bar by bar, driving the **same** `PaperTradingEngine` over
  historical bars rather than reimplementing execution (§35).
- Lookahead prevention is structural, not advisory: the strategy callback
  receives `bars[0..i]` only, so a strategy cannot read a future bar even by
  accident. A test confirms a strategy indexing past its history gets an
  `IndexError` rather than tomorrow's price.
- Every run records the §82 audit disclosures — fee model, slippage model,
  fill model, lookahead prevention, intrabar assumption, liquidity assumption,
  survivorship note. A run without them is not a meaningful result and the
  tests assert all seven are present and non-trivial.
- Open positions are force-closed at the end of the window, so a result
  reflects realised outcomes rather than an open position's paper gain.
- `metrics.py` implements the §41 set once (net P&L, win/loss rate, profit
  factor, expectancy, Sharpe, Sortino, max drawdown, exposure, fees,
  slippage). Undefined metrics return `None`, never a fabricated number:
  profit factor with no losses is undefined rather than infinite, and Sharpe
  on a flat curve is undefined rather than zero.
- A test pins §41's own caution: nine small wins and one large loss shows a
  90% win rate *and* a negative expectancy, so win rate can never be mistaken
  for the objective.

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
| Backend unit | 399 | pass |
| Backend API + WebSocket integration | 41 | pass |
| Backend database integration | 46 | pass (real PostgreSQL 16); skip without one |
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
- Live feature computation on the stream path (persist candle + compute
  latest features on every closed bar) has only been exercised with a mocked
  stream in unit tests; it has not run against a real multi-hour live
  connection. `wma` and `cci` use a per-row Python callback under pandas
  `rolling().apply()`, which is O(n·period) — fine at today's data volumes,
  worth profiling once years of 15m history are involved.
- No frontend surface shows technical features or market structure yet; the
  Data page (Phase 6) covers candle coverage only. A Market/Signals page is
  the natural home for both and is deferred to when Phase 13 (signal fusion)
  needs one, rather than building a second interim page now.
- Market structure's swing-detection window (`SWING_WINDOW = 5`) and false-
  breakout confirmation window (`FALSE_BREAKOUT_WINDOW = 3`) are reasonable
  defaults, not validated against real price action yet — that validation is
  what §22's automatic pattern validation (Tier 2, Phase 21) exists for, and
  applies to structure signals feeding the model the same way it applies to
  chart patterns.
- The LightGBM baseline has not been trained on real market history — every
  test uses synthetic data (deterministic for plumbing correctness, or a
  crafted momentum series for "does this pipeline learn anything at all").
  Whether it clears `min_validation_accuracy`/`min_validation_macro_f1` on
  real BTC/ETH/BNB history, and what those bars *should* be, is unknown until
  a real backfill (Phase 6) and feature computation (Phase 7/8) have run and
  someone actually calls `POST /models/train`.
- The label horizon (4 candles) and neutral-band threshold (0.3%) are
  documented starting points, not tuned values — nothing in this system
  currently searches over them, which is deliberate: an untracked parameter
  search is exactly the p-hacking risk §22's experiment log exists to guard
  against, and that search belongs in a later phase with the logging to match.
- No model has been promoted to PRODUCTION, and nothing in this system can
  place an order yet regardless (Phase 10/11 don't exist) — every prediction
  Phase 9 can produce is `shadow_mode=True` by construction, not by policy
  choice that could be forgotten.
- `POSTGRES_PASSWORD` is fixed when PostgreSQL first initialises its data
  directory; changing it in `.env` afterwards causes an authentication failure
  until the server password is changed to match (see TROUBLESHOOTING.md).

## Next phase

**Phase 10 — risk engine.**

The highest-authority component (§31): no model, no LLM, no frontend request
may bypass it. Every risk parameter is already defined once, frozen, in
`app/config/risk_config.py` (Phase 1) — Phase 10 is the engine that enforces
those limits, not a place that redefines them.

1. `APPROVED | REJECTED | PAUSED` decisions with a human-readable reason,
   checked against every §31 parameter: exposure, daily loss, drawdown,
   consecutive losses, slippage/spread protection, stale-data protection
   (already computable via `BinanceService.data_is_stale`, Phase 5),
   API-failure protection (already tracked via `consecutive_failures`,
   Phase 5), model-health protection.
2. Position sizing (§32): balance, risk percentage, stop distance, fees,
   slippage, exchange filters (`SymbolFilters`, Phase 5) — `REJECT:
   TRADE_NOT_ECONOMIC` is an expected outcome at this account size, not an
   edge case to special-case away.
3. `risk_events` persisted for every rejection/pause, not only approvals.
4. `risk` API un-pended: current state, rejection history, live parameter
   values (read-only — changing a risk parameter is a Settings concern, not
   this engine's).

No martingale (§56), no guaranteed-profit language anywhere it touches the
frontend contract (§57). Then Phase 11 (paper trading simulator) and Phase 12
(backtesting engine), the first two components that can actually act on a
risk engine's APPROVED decision.
