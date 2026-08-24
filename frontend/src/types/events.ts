/**
 * WebSocket event contract — mirrors `backend/app/core/events.py` (§13).
 * Keep the two in sync; the backend is authoritative.
 */
export const EVENT_TYPES = [
  'market_update',
  'ticker_update',
  'candle_closed',
  'signal_created',
  'signal_updated',
  'order_created',
  'order_updated',
  'order_filled',
  'position_updated',
  'portfolio_updated',
  'risk_event',
  'model_status',
  'training_status',
  'backtest_status',
  'news_update',
  'system_status',
  'log_event',
  'heartbeat',
  'subscription_updated',
  'error',
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export interface AppEvent<T = Record<string, unknown>> {
  event: EventType;
  timestamp: string;
  data: T;
}

export interface LogEventData {
  level: string;
  component: string;
  event_type: string;
  message: string;
}
