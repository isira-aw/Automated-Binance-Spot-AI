# Project status

Last updated: 2026-08-25 · Track: **MVP / Tier 1** · Phase 16 of 20

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
- Implemented pages: Dashboard, System, Settings, Logs, Data (Phase 6),
  Signals and Models (Phase 14, following Phase 13's signal fusion).
- REST client with typed errors; WebSocket client with exponential-backoff
  reconnect and heartbeat replies. `apiPost` now carries an optional JSON
  body, needed once an endpoint (`/signals/generate`, `/models/train`) takes
  parameters rather than acting on nothing.
- Tier labelling: the UI reports which components influence an *executed*
  trade (today: none, since nothing yet wires a signal to an order) —
  distinct from a signal simply having been generated, which the Dashboard's
  "Latest signals" panel and the Signals page now show happening.
- Signals page: generate a fused signal for a chosen symbol/timeframe, browse
  recent signals, and expand any row to its full component breakdown and
  reason codes — the §79/§80 decision chain made visible for the first time.
- Models page: the LightGBM registry and a training trigger, reusing the
  Phase 9 API. `/models` moved from the "Tier 2 — intelligence layer" nav
  section to "Tier 1 — core": it is the Tier 1 baseline model, not a Tier 2
  research component, and the nav grouping was inconsistent with that.
- Verified against a live backend + database in this session (not just
  `tsc`/`eslint`/`vitest`): seeded synthetic candles, computed features,
  trained a model, then drove the Signals and Models pages in a real browser
  — generate-signal, the component-detail expand, and the Dashboard's latest-
  signals panel all round-trip correctly end to end.

**Phase 15 — Risk and Backtesting: backend wiring + frontend pages**
- Discovered mid-phase that "already-built API surface" was wrong for two of
  the four pages this phase set out to wire: `risk` had a real, tested API
  (Phase 10) with just no UI, but `orders`/`positions`/`trades` have no REST
  namespace *or* persistence wiring at all -- `PaperOrder`/`PaperPosition`/
  `Trade` are Phase 2 schema with nothing that has ever written a row to
  them, because Phase 11 built the paper-trading simulator as a pure
  in-memory library with no execution entrypoint, manual or automatic. Built
  what was actually ready (Risk page, and a new Backtesting backend +
  page); re-scoped `orders`/`positions`/`trades` honestly to "Phase 15b —
  paper trading execution API" in `PENDING_PAGES` rather than build a rushed
  execution/persistence layer for money-shaped data under time pressure.
- RiskPage: active limits, system-level trading-permitted state, and
  decision history from the existing `risk` API (Phase 10) -- read-only,
  since the engine enforces limits, it does not own their values.
- `app/backtesting/service.py` (new): the piece Phase 12 didn't build --
  orchestrates a real backtest run and persists it. Loads candles and
  precomputed technical features for a range, runs the same `BacktestEngine`
  Phase 12 tested, and persists `BacktestRun`/`BacktestTrade` (Phase 2
  schema, unused until now). `backtests` API un-pended: `POST
  /backtests/run`, `GET /backtests`, `GET /backtests/{id}`.
- The backtest's reference strategy is deliberately technical-only, not the
  two-component fusion Phase 13 built for live signals: `predict_latest`
  only ever scores the *latest* bar, and there is no per-bar LightGBM
  inference path today. Reusing `app/signals/fusion.py` with a single
  `TECHNICAL` component (weight 1.0) means the fusion logic itself is not
  reimplemented, only the model contribution is absent -- a real, disclosed
  restriction, not a silent approximation. Extending backtests to include
  LightGBM is deferred to when a batch/at-time prediction path exists.
  Stop-loss/take-profit are ATR-based (`atr_stop_multiplier`/
  `atr_reward_multiplier`, new `BacktestConfig` fields) since a long entry
  needs a concrete stop distance for position sizing to mean anything
  (`app/risk/position_sizing.py` rejects a sizing request without one).
- Exchange filters for sizing/rounding come from live-cached exchange
  metadata when available, falling back to "no constraint" and recording
  which one was used in the persisted `assumptions` -- never a guessed
  filter set standing in for real exchange rules.
- A run is bounded by a new `max_bars` config cap (default 5000) and
  rejected with a clear error over it, rather than accepting an
  unboundedly long synchronous request.
- BacktestingPage: submit a run, browse recent runs, and inspect one in
  full -- the §41 metric set, all seven §82 audit disclosures, and the
  trade log. A result is never shown without its disclosures.
- Verified end to end against a live backend + database: seeded a strong
  synthetic uptrend, ran a backtest via the API and via the browser UI,
  confirmed real trades with real fees/slippage applied and metrics that
  make sense for the input (high win rate on a low-noise uptrend, not a
  red flag). 6 new DB integration tests for the service; 526 backend tests
  total, all passing.

**Phase 15b — paper trading execution API**
- `app/paper_trading/account.py` (new): the execution entrypoint Phase 11
  never built. Wraps the existing `PaperTradingEngine`/`Portfolio` (no
  reimplementation) with a persistence layer either side of every action --
  rehydrate current state from the database, run the real engine, persist
  what it did. Manual entry only, a deliberate scope boundary stated in the
  module's own docstring: nothing here is triggered automatically by a
  generated `Signal`.
- The rehydration is the hard part, and the one this phase's tests target
  directly: `quote_balance`/`realised_pnl`/`total_fees` are *derived* from
  the `trades` ledger and currently-open `paper_positions` rows every time,
  never read from a separately stored balance that could drift from its own
  history (same trade-off the `xmax` upsert trick and health aggregation
  make elsewhere). Critically, the risk engine's per-symbol cooldown and
  consecutive-loss-streak protections are *also* rehydrated from the same
  ledger before every new evaluation -- without that, both protections would
  silently reset on every separate API call, since each one builds a brand
  new in-memory `PaperTradingEngine` from scratch. Two of the nine new DB
  integration tests exist specifically to prove this: opening, closing, and
  immediately reopening the same symbol across three separate calls still
  trips the cooldown; two losing trades closed across separate calls still
  trip the loss-streak halt on a third attempt.
- `peak_equity` (needed for the drawdown halt) is the one honestly
  approximate part: without a continuous mark-to-market loop (no scheduler
  exists yet), it can only be reconstructed from equity recorded at past
  actions (a new use of the Phase 2 `portfolio_snapshots` table, written on
  every open/close), which under-counts any intrabar peak between two
  actions. Documented below, not hidden -- and the error direction is the
  wrong one for a safety feature (a peak that's actually higher than
  reconstructed means real drawdown is under-reported).
- `app/binance/filters.py` (new): the exchange-filter fallback logic
  extracted out of Phase 15's `backtesting/service.py` so paper trading
  reuses it rather than a second copy -- live-cached metadata when
  available, otherwise "no constraint", disclosed either way.
- `orders`/`positions`/`trades` API un-pended: `GET`/`POST /orders`,
  `GET /positions`, `POST /positions/{symbol}/close`, `GET /trades`. A risk
  rejection on `POST /orders` returns 409 with the engine's rule and reason
  (also persisted to `risk_events`, visible at `GET /risk/events`) rather
  than a 200 wrapping a failure.
- PositionsPage (place/close a paper trade), OrdersPage (fill history), and
  TradesPage (closed ledger) — `orders`/`positions`/`trades` finally have
  real pages instead of `PENDING_PAGES` placeholders.
- Verified two ways: 9 new DB integration tests against real PostgreSQL
  covering open/close/rehydration/cooldown/loss-streak/rejection (the
  correctness-critical part), and a live backend + browser session
  confirming the full request path -- routes, empty states, and a Binance-
  unreachable error propagating cleanly to the UI without a crash (Binance
  itself is unreachable from this session, same limitation noted since
  Phase 5, so a full live fill could not be exercised end-to-end here).
  Full backend suite: 535 passing (427 unit / 41 API+WS / 67 DB
  integration).

**Phase 16 — system monitoring and the scheduler**
- `app/scheduler/service.py` (new): the unattended heartbeat the health
  endpoint has reported `NOT_IMPLEMENTED` for since Phase 3. A small,
  explicit `asyncio` task -- not a new scheduling framework -- since one
  periodic job is what exists to run. Started and stopped from
  `app/lifespan.py` alongside every other component, and started even if
  Binance failed to connect at startup: it degrades gracefully per tick
  rather than needing Binance up front.
- Its one job so far: `monitor_open_positions` (`app/paper_trading/
  account.py`), the continuous check a manually-placed paper position
  never had before this phase. Previously a stop-loss, take-profit, or
  trailing stop on an open paper position was only ever evaluated at the
  moment someone called `close` -- everything between two manual actions
  was invisible to the system. Each tick fetches a live price per open
  symbol and reuses `exit_reason_for_bar`/`update_trailing_stop` from
  Phase 11's fills module directly (`high=low=price` correctly reduces the
  OHLC-bar check to a live-price comparison, no separate implementation),
  closing at the exact stop/target price if triggered -- same principle as
  a backtest, an exit fills at the trigger price, not whatever the ticker
  reads a moment later. `close_paper_trade` gained an optional
  `reference_price` override for this; the manual API path is unaffected
  (still fetches a fresh live price by default).
- Every tick also marks the account to market and writes a
  `portfolio_snapshots` row when at least one position could be priced,
  directly improving Phase 15b's disclosed `peak_equity` approximation
  (more snapshot events between manual actions means less under-counted
  drawdown headroom).
- A single symbol's price fetch failing degrades that symbol only (logged,
  skipped) -- it does not stop the rest of the open book from being
  monitored, and a whole tick failing does not stop the loop, matching the
  "a failure here must not stop the stream" principle the market-data
  bridge already used (§44).
- `/system/health`'s `scheduler` entry is now a real probe (`ONLINE` with
  tick count / last-tick timestamp, `DEGRADED` with the last tick's error,
  `OFFLINE` if stopped, `DISABLED` if configured off) instead of the
  `NOT_IMPLEMENTED` placeholder. While making this accurate, also fixed
  `risk_engine` and `technical_engine`, which had been reporting
  `NOT_IMPLEMENTED` since Phase 3 despite Phase 7/8/10 actually building
  them -- both are pure computation over already-checked dependencies, so a
  static `ONLINE` is correct. `trading_engine` stays `NOT_IMPLEMENTED`,
  correctly: no automated signal-to-order execution exists (Phase 15b is
  manual-only).
- No frontend change was needed: the Dashboard/System pages already render
  `health.components` generically from whatever the API returns, so the
  new `scheduler`/`risk_engine`/`technical_engine` statuses show up without
  any page-specific code.
- Verified three ways: 8 new DB integration tests for `monitor_open_positions`
  (stop/target triggers fill at the exact trigger price with slippage
  applied, trailing stop ratchets and never lowers, one symbol's price
  failure doesn't block others, a snapshot is written, a position closed
  between ticks is a clean no-op); 9 new unit tests for `SchedulerService`
  itself (start/stop lifecycle, a failing tick doesn't stop the loop and
  clears on the next success, all four health states) using a monkeypatched
  `session_scope`/`monitor_open_positions` rather than a real database,
  since the loop's own bookkeeping is what's under test there; and a live
  backend session confirming `scheduler` actually reports `ONLINE` with an
  incrementing `tick_count` at the configured 30s interval against the real
  database, with zero open positions to monitor (a real fill still can't be
  exercised, per the Phase 5 Binance-connectivity limitation noted
  throughout). Full backend suite: 552 passing (436 unit / 41 API+WS / 75
  DB integration).

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

**Phase 13 — signal fusion (technical + LightGBM)**
- `app/signals/technical_score.py`: maps the Phase 7/8 indicator and market
  structure features into a single technical opinion on the unified [0,1]
  scale (§30a). Four sub-signals (trend, momentum, directional movement,
  structure) are averaged only over the ones actually available; with none
  available it returns a neutral `0.5` score at `0.0` confidence rather than
  guessing. Confidence is discounted both by how many sub-signals fired
  (completeness) and by a volatility penalty, so a technically "confident"
  score computed from a thin feature set or during a high-volatility regime
  is never reported with unwarranted certainty.
- `app/signals/fusion.py`: combines any number of `ComponentScore`s (Tier 1
  uses exactly two: `TECHNICAL`, `LIGHTGBM`) into one `BUY | SELL | WAIT |
  NO_VALID_SETUP` decision (§54). An inactive component (no model registered,
  no features computed yet) is excluded from the weighted average entirely —
  it is never scored as a neutral `0.5` opinion, which would silently dilute
  the fused confidence toward "no signal" instead of honestly reporting "no
  opinion". `NO_VALID_SETUP` fires only when there is nothing to evaluate at
  all; a merely low-confidence or too-near-neutral fusion is `WAIT`, a
  distinct and more informative outcome.
- `app/signals/service.py` orchestrates both against the database: it reads
  the latest `TechnicalFeature` row and the best available `ModelVersion`
  (`VALIDATED` preferred over `CANDIDATE` — there is no `PRODUCTION` concept
  reachable yet, since nothing has been promoted through Phase 12's
  backtesting), reuses Phase 9's `predict_latest`/`fusion_score_from_probabilities`
  for the LightGBM leg, fuses, and persists a `Signal` with its
  `SignalComponent` children. The natural key (`symbol`, `timeframe`,
  `open_time`, `strategy_version`, `venue`) is upserted, so re-running fusion
  for a bar already evaluated updates the same row rather than growing a
  duplicate history (§80 reproducibility). `WAIT` and `NO_VALID_SETUP` are
  persisted like any other outcome (§54) — only the complete absence of a
  technical feature row to anchor to (nothing computed yet for that
  symbol/timeframe) skips persistence, since there is no `open_time` to key
  it against.
- `signals` API un-pended: `GET /signals` (recent, filterable), `GET
  /signals/latest`, `POST /signals/generate`. Literal routes are registered
  before any dynamic ones, per the Phase 9 route-ordering lesson.
- Signal generation never touches the risk engine, position sizing, or order
  placement — those stay out of scope until the pieces they depend on
  (Phase 10/11, already built) are wired together in a later phase. A
  generated signal's `risk_decision`/`risk_reason` columns exist in the
  schema but are left `NULL` here; nothing sets them yet.

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
| Backend unit | 436 | pass |
| Backend API + WebSocket integration | 41 | pass |
| Backend database integration | 75 | pass (real PostgreSQL 16); skip without one |
| Frontend (vitest) | 14 | pass |

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
- No frontend surface shows technical features or market structure directly
  yet (raw indicator/structure values, not just the fused score) — the
  Signals page (Phase 14) shows the technical component's contribution to a
  fused signal, but a dedicated Market page for browsing indicators candle by
  candle is still pending (`market` remains in `PENDING_PAGES`).
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
- Signal fusion (Phase 13) is Tier 1 scope only: exactly `TECHNICAL` and
  `LIGHTGBM` components, per §30/§86. `PATTERN`, `REGIME`, `TRANSFORMER`,
  `NEWS`, `FUNDAMENTAL`, `LOCAL_LLM`, and `CLAUDE` component kinds already
  exist in the `SignalComponentKind` enum (Phase 1 schema) but nothing
  produces them yet; there is no placeholder standing in for them in the
  fused score.
- A generated `Signal` never has its `risk_decision`/`risk_reason` columns
  populated — signal generation does not call the risk engine (Phase 10).
  Wiring a signal through risk evaluation and into an order is a later
  phase's job, once there is an order to place (Phase 11 already exists as
  paper trading, but nothing yet drives it from a live signal automatically).
- Signal fusion has only been exercised against synthetic candles and a
  LightGBM model trained on synthetic data, same as Phase 9 — the fused
  score's real-world behaviour on BTC/ETH/BNB history is unknown until a
  real backfill, real feature computation, and a real training run precede it.
- **Paper trading execution is manual only.** Phase 15b built the
  entrypoint (`app/paper_trading/account.py`) and the `orders`/
  `positions`/`trades` API/UI, but nothing places a paper trade
  automatically from a generated `Signal` — that was a deliberate scope
  boundary this phase made explicit rather than defaulting into silently.
  A live signal and a paper position are still two disconnected things a
  person has to bridge by hand.
- Paper trading's `peak_equity` (the drawdown halt's input) is still an
  approximation, improved but not eliminated by Phase 16: the scheduler
  now marks positions to market and snapshots equity every 30 seconds
  (configurable, `scheduler.interval_seconds`) rather than only at manual
  open/close, but a true peak between two ticks — a spike and reversal
  entirely inside that window — is still invisible. The error direction is
  still the safe one for a drawdown halt (under-reporting the peak
  under-reports drawdown, it never overstates safety), and the window is
  now bounded by the tick interval instead of by how often a person happens
  to act.
- Paper trading has never been exercised against a live Binance price feed
  from this environment (same limitation noted for the Binance connector
  since Phase 5) — `open_paper_trade`/`close_paper_trade`'s correctness is
  proven against a fake ticker in 9 DB integration tests, and the API/UI
  request path is proven live end-to-end up to the point of the Binance
  call itself, but a real fill has not happened yet.
- The Phase 15 backtest reference strategy is technical-only, not the
  two-component fusion Phase 13 built for live signals — `predict_latest`
  only scores the latest bar, and there is no per-bar/at-time LightGBM
  inference path for a historical replay yet. A backtest run's `metrics`
  therefore describe the technical component alone, not the same decision
  process a live-generated `Signal` used.
- The ATR-based stop/target multipliers (`atr_stop_multiplier`,
  `atr_reward_multiplier`) that make the backtest reference strategy's
  entries sizeable are documented starting points, not tuned values — same
  caveat as the label horizon/threshold and the fusion weights.
- A backtest run is synchronous (unlike training or a signals generate call,
  it can process thousands of bars) and bounded by `max_bars` (default
  5000) rather than backgrounded with a status-poll pattern; a range over
  the cap is rejected rather than silently truncated or left to time out.
- The scheduler's only job is monitoring existing open positions — it does
  not compute technical features on a timer (that stays event-driven off
  the live candle stream, Phase 5/8, unchanged) and it does not turn a
  generated `Signal` into a new order. Automatic signal-to-order execution
  is still the open policy decision flagged since Phase 15 and deliberately
  left unmade; the scheduler's existence doesn't answer it, it just gives a
  future answer somewhere to run.
- The scheduler is a single `asyncio` task on a fixed interval, not a
  distributed or persistent job queue — if the backend process restarts,
  the loop restarts from tick 1 with no memory of the previous run's tick
  count (state that was never load-bearing: every tick rehydrates its own
  data from the database, same as every other paper-trading action).

## Next phase

**Phase 17 — end-to-end testing.**

Every Tier 1 piece now exists individually, tested at the unit and DB
integration layer: market data → features → structure → LightGBM → fused
signal (Phase 13), risk-gated manual paper execution (Phase 15b), and an
unattended loop keeping positions monitored between actions (Phase 16).
None of it has been tested as one continuous path — seed candles, compute
features, generate a signal, place a paper trade from it by hand, let the
scheduler carry it to a stop/target exit, and check the resulting `Trade`
and metrics are what the chain of individual pieces should produce.

1. A true end-to-end test (or a small suite of them) exercising that full
   chain against a real database, asserting on the final state rather than
   any one component's isolated behaviour — the kind of test that would
   have caught a units mismatch or a sign error between two correctly-unit-
   tested pieces that nonetheless disagree at their seam.
2. Frontend E2E: a browser-driven pass (Playwright, matching what this
   session already used for manual verification) covering the same chain
   through the actual UI — Signals → Positions → Trades — codified as a
   repeatable test rather than a one-off manual session.
3. Whatever this surfaces about the seams between phases (naming
   mismatches, an assumption one phase made that the next didn't share) is
   the actual point of this phase — Phase 17 is a correctness pass across
   the whole system, not new capability.
