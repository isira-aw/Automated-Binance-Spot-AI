/** REST response types — mirrors `backend/app/schemas` (§60). */

export type ComponentHealth =
  | 'ONLINE'
  | 'OFFLINE'
  | 'DEGRADED'
  | 'ERROR'
  | 'DISABLED'
  | 'NOT_IMPLEMENTED';

export interface HealthResponse {
  overall: ComponentHealth;
  checked_at: string;
  components: Record<string, { status: ComponentHealth; detail?: string } & Record<string, unknown>>;
}

export interface VersionResponse {
  app_name: string;
  api_version: string;
  environment: string;
  strategy_version: string;
  feature_version: string;
  schema_revision: string | null;
}

export type TradingMode = 'BACKTEST' | 'PAPER' | 'BINANCE_TESTNET' | 'LIVE';
export type EngineState = 'RUNNING' | 'PAUSED' | 'EMERGENCY_STOP';

export interface SystemStateResponse {
  mode: TradingMode;
  engine_state: EngineState;
  live_armed: boolean;
  live_trading_enabled: boolean;
  last_shutdown_at: string | null;
  model_registry_ok: boolean;
  model_registry_problems: Array<Record<string, string>>;
}

export interface TierStatusResponse {
  tier1_components: string[];
  tier2_components: string[];
  tier2_enabled: Record<string, boolean>;
  /** Components that currently influence live trading decisions (§14). */
  influencing_signals: string[];
}

export interface RiskConfigResponse {
  max_risk_per_trade: number;
  max_position_size: number;
  max_asset_exposure: number;
  max_portfolio_exposure: number;
  max_simultaneous_positions: number;
  max_daily_loss: number;
  max_drawdown: number;
  max_consecutive_losses: number;
  max_slippage: number;
  spread_protection: number;
  volatility_protection: number;
  stale_data_protection_seconds: number;
  api_failure_protection_threshold: number;
  model_health_protection: boolean;
  cooldown_period_seconds: number;
}

export interface SettingsResponse {
  environment: string;
  trading: {
    assets: string[];
    timeframes: string[];
    decision_timeframe: string;
    entry_timeframe: string;
    mode: TradingMode;
    live_trading_enabled: boolean;
    minimum_confidence: number;
    maker_fee: number;
    taker_fee: number;
  };
  risk: RiskConfigResponse;
  paper_trading: Record<string, unknown>;
  backtesting: Record<string, unknown>;
  models: Record<string, unknown>;
  binance: { testnet: boolean; credentials_configured: boolean; recv_window_ms: number };
  tiers: TierStatusResponse;
}

/** The single error envelope every endpoint uses (§100). */
export interface ApiErrorBody {
  error: { code: string; message: string; metadata?: Record<string, unknown> | null };
}

// --- Market data (§17, §59) -------------------------------------------------

export interface CoverageEntry {
  symbol: string;
  timeframe: string;
  source: string;
  first_candle_open: string | null;
  last_candle_open: string | null;
  candle_count: number;
  missing_candles: number;
  last_integrity_check: string | null;
  is_clean: boolean | null;
}

export interface IngestionResultEntry {
  symbol: string;
  timeframe: string;
  pages_fetched: number;
  candles_inserted: number;
  candles_updated: number;
  reached_present: boolean;
  stopped_reason: string;
  error: string | null;
}

export interface BackfillJobResponse {
  started_at: string;
  finished_at: string | null;
  running: boolean;
  error: string | null;
  total_candles_inserted: number;
  results: IngestionResultEntry[];
}

export interface IntegrityReportEntry {
  symbol: string;
  timeframe: string;
  candle_count: number;
  expected_count: number | null;
  missing_candles: number;
  duplicate_open_times: number;
  misaligned_timestamps: string[];
  ohlc_violations: string[];
  non_positive_values: string[];
  abnormal_moves: string[];
  is_clean: boolean;
  checked_at: string;
}

// --- Model registry (§39, §59) ---------------------------------------------

export type ModelStatus = 'CANDIDATE' | 'VALIDATED' | 'PRODUCTION' | 'ARCHIVED' | 'REJECTED';

export interface ModelVersionOut {
  model_id: string;
  version: string;
  model_type: string;
  status: ModelStatus;
  symbol: string | null;
  timeframe: string | null;
  feature_version: string;
  artifact_sha256: string | null;
  training_data_range: Record<string, unknown> | null;
  validation_range: Record<string, unknown> | null;
  test_range: Record<string, unknown> | null;
  hyperparameters: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  created_at: string;
  promoted_at: string | null;
  notes: string | null;
}

export interface TrainRequest {
  symbol: string;
  timeframe: string;
}

export interface TrainingOutcomeOut {
  job_id: string;
  status: string;
  model_version: string | null;
  registry_status: string | null;
  error: string | null;
  metrics: Record<string, unknown> | null;
}

export interface TrainingStatusOut {
  running: boolean;
  outcome: TrainingOutcomeOut | null;
}

// --- Signal fusion (§30, §59) -----------------------------------------------

export type SignalAction = 'BUY' | 'SELL' | 'EXIT' | 'WAIT' | 'NO_VALID_SETUP';
export type SignalComponentKind =
  | 'TECHNICAL'
  | 'PATTERN'
  | 'REGIME'
  | 'LIGHTGBM'
  | 'TRANSFORMER'
  | 'NEWS'
  | 'FUNDAMENTAL'
  | 'LOCAL_LLM'
  | 'CLAUDE';

export interface SignalComponentOut {
  kind: SignalComponentKind;
  score: number;
  weight: number;
  confidence: number | null;
  version: string | null;
  active: boolean;
  details: Record<string, unknown> | null;
}

export interface SignalOut {
  id: number;
  symbol: string;
  timeframe: string;
  open_time: string;
  generated_at: string;
  action: SignalAction;
  score: number;
  confidence: number;
  reason_codes: string[];
  strategy_version: string;
  fusion_method: string;
  reference_price: number | null;
  risk_decision: string | null;
  risk_reason: string | null;
  venue: string;
  components: SignalComponentOut[];
}

export interface GenerateSignalRequest {
  symbol: string;
  timeframe: string;
}

// --- Risk (§31, §59) ---------------------------------------------------------

export interface RiskParametersOut {
  max_risk_per_trade: number;
  max_position_size: number;
  max_asset_exposure: number;
  max_portfolio_exposure: number;
  max_simultaneous_positions: number;
  max_daily_loss: number;
  max_drawdown: number;
  max_consecutive_losses: number;
  max_slippage: number;
  spread_protection: number;
  volatility_protection: number;
  stale_data_protection_seconds: number;
  api_failure_protection_threshold: number;
  model_health_protection: boolean;
  cooldown_period_seconds: number;
}

export interface RiskEventOut {
  id: number;
  timestamp: string;
  venue: string;
  symbol: string | null;
  decision: string;
  rule: string;
  reason: string;
  details: Record<string, unknown> | null;
}

export interface RiskStateOut {
  trading_permitted: boolean;
  decision: string;
  rule: string | null;
  reason: string | null;
  engine_state: string;
  checked_at: string;
}

// --- Backtests (§35, §41, §82, §59) ------------------------------------------

export interface BacktestRunRequest {
  symbol: string;
  timeframe: string;
  range_start: string;
  range_end: string;
}

export interface BacktestTradeOut {
  symbol: string;
  side: string;
  quantity: number;
  entry_time: string;
  entry_price: number;
  exit_time: string;
  exit_price: number;
  gross_pnl: number;
  fees: number;
  slippage_cost: number;
  net_pnl: number;
  return_pct: number;
  mae: number | null;
  mfe: number | null;
  exit_reason: string | null;
}

export interface BacktestRunOut {
  id: number;
  job_id: string;
  status: string;
  symbols: string[];
  timeframe: string;
  range_start: string;
  range_end: string;
  initial_capital: number;
  maker_fee: number;
  taker_fee: number;
  slippage_bps: number;
  strategy_version: string;
  feature_version: string | null;
  config: Record<string, unknown> | null;
  metrics: Record<string, unknown> | null;
  assumptions: Record<string, string> | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_at: string;
  trades: BacktestTradeOut[];
}

export interface BacktestRunSummaryOut {
  id: number;
  job_id: string;
  status: string;
  symbols: string[];
  timeframe: string;
  range_start: string;
  range_end: string;
  strategy_version: string;
  metrics: Record<string, unknown> | null;
  created_at: string;
}

// --- Paper trading execution (§11B, §31, §41, §59) --------------------------

export interface OpenOrderRequest {
  symbol: string;
  stop_price: number;
  take_profit?: number;
  trailing_distance?: number;
  signal_id?: number;
}

export interface PaperOrderOut {
  id: number;
  client_order_id: string;
  signal_id: number | null;
  symbol: string;
  side: string;
  order_type: string;
  status: string;
  quantity: number;
  price: number | null;
  filled_quantity: number;
  average_fill_price: number | null;
  fee: number;
  submitted_at: string;
  strategy_version: string | null;
}

export interface PaperPositionOut {
  id: number;
  symbol: string;
  status: string;
  quantity: number;
  entry_price: number;
  entry_time: string;
  exit_price: number | null;
  exit_time: string | null;
  stop_loss: number | null;
  take_profit: number | null;
  trailing_stop: number | null;
  unrealised_pnl: number | null;
  realised_pnl: number | null;
  fees_paid: number;
  signal_id: number | null;
  strategy_version: string | null;
}

export interface TradeOut {
  id: number;
  venue: string;
  symbol: string;
  position_id: number | null;
  signal_id: number | null;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  entry_time: string;
  exit_time: string;
  gross_pnl: number;
  fees: number;
  slippage_cost: number;
  net_pnl: number;
  return_pct: number;
  mae: number | null;
  mfe: number | null;
  exit_reason: string | null;
  strategy_version: string | null;
  model_version: string | null;
}
