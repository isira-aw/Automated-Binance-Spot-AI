import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import type { SettingsResponse } from '@/types/api';

const RISK_DESCRIPTIONS: Record<string, string> = {
  max_risk_per_trade: 'Fraction of equity risked on one trade',
  max_position_size: 'Max fraction of equity in one position',
  max_asset_exposure: 'Max fraction of equity exposed to one asset',
  max_portfolio_exposure: 'Max fraction of equity deployed overall',
  max_simultaneous_positions: 'Concurrent open positions allowed',
  max_daily_loss: 'Daily loss fraction that pauses trading',
  max_drawdown: 'Peak-to-trough drawdown that pauses trading',
  max_consecutive_losses: 'Losing trades before a cooldown',
  max_slippage: 'Max tolerated slippage vs. signal price',
  spread_protection: 'Max tolerated bid/ask spread',
  volatility_protection: 'Max tolerated ATR/price ratio',
  stale_data_protection_seconds: 'Market data older than this is never traded on',
  api_failure_protection_threshold: 'Consecutive API failures before pausing',
  model_health_protection: 'Block trading when the model is unhealthy',
  cooldown_period_seconds: 'Minimum wait after an exit, per symbol',
};

export function SettingsPage() {
  const settings = useApi<SettingsResponse>('/settings');

  if (settings.error) return <ErrorNotice error={settings.error} />;
  if (!settings.data) return <p className="text-sm text-slate-500">Loading…</p>;

  const { trading, risk, binance, models } = settings.data;

  return (
    <div className="space-y-6">
      <Panel title="Trading">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Assets" value={trading.assets.join(', ')} />
          <Field label="Timeframes" value={trading.timeframes.join(', ')} />
          <Field label="Decision timeframe" value={trading.decision_timeframe} />
          <Field label="Entry timeframe" value={trading.entry_timeframe} />
          <Field label="Mode" value={trading.mode} />
          <Field label="Minimum confidence" value={trading.minimum_confidence.toFixed(2)} />
          <Field label="Maker fee" value={`${(trading.maker_fee * 100).toFixed(3)}%`} />
          <Field label="Taker fee" value={`${(trading.taker_fee * 100).toFixed(3)}%`} />
          <Field label="Live trading" value={trading.live_trading_enabled ? 'enabled' : 'disabled'} />
        </div>
        <p className="mt-4 text-[11px] text-slate-500">
          Settings are read-only in the UI until the configuration write API is implemented. They
          are edited through <span className="font-mono">.env</span> and the config module today.
        </p>
      </Panel>

      <Panel title="Risk limits — authoritative">
        <p className="mb-3 text-[11px] text-slate-500">
          These are the single source of truth. No model, no LLM, and no frontend request can
          bypass them.
        </p>
        <table className="w-full text-sm">
          <tbody>
            {Object.entries(risk).map(([key, value]) => (
              <tr key={key} className="border-t border-surface-800">
                <td className="py-1.5 font-mono text-[12px] text-slate-300">{key}</td>
                <td className="py-1.5 text-right font-mono text-slate-100">{String(value)}</td>
                <td className="py-1.5 pl-4 text-[11px] text-slate-500">
                  {RISK_DESCRIPTIONS[key] ?? ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Binance">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Testnet" value={binance.testnet ? 'yes' : 'no'} />
            <Field
              label="Credentials"
              value={binance.credentials_configured ? 'configured' : 'not configured'}
            />
            <Field label="recvWindow" value={`${binance.recv_window_ms} ms`} />
          </div>
          <p className="mt-3 text-[11px] text-slate-500">
            API keys never reach the browser. Withdrawal permission is never required and no
            withdrawal function exists anywhere in this system.
          </p>
        </Panel>

        <Panel title="Models">
          <div className="grid gap-4 sm:grid-cols-2">
            {Object.entries(models).map(([key, value]) => (
              <Field key={key} label={key.replace(/_/g, ' ')} value={String(value)} />
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="metric-label">{label}</div>
      <div className="font-mono text-sm text-slate-200">{value}</div>
    </div>
  );
}
