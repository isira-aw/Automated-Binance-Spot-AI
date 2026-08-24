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
