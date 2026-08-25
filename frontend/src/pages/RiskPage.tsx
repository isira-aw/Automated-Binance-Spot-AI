import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Metric } from '@/components/ui/Metric';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import type { RiskEventOut, RiskParametersOut, RiskStateOut } from '@/types/api';

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

const DECISION_STYLES: Record<string, string> = {
  REJECTED: 'bg-bearish/15 text-bearish border-bearish/30',
  PAUSED: 'bg-caution/15 text-caution border-caution/30',
};

/**
 * The risk engine's active limits and decision history (§31, §59).
 *
 * Read-only by design: the engine enforces limits, it does not own their
 * values, so there is no control here that changes one -- that is a
 * Settings concern.
 */
export function RiskPage() {
  const state = useApi<RiskStateOut>('/risk/state', 10_000);
  const parameters = useApi<RiskParametersOut>('/risk/parameters');
  const events = useApi<RiskEventOut[]>('/risk/events?limit=50', 15_000);

  if (parameters.error) return <ErrorNotice error={parameters.error} />;

  const params = parameters.data;
  const rows = events.data ?? [];

  return (
    <div className="space-y-6">
      <Panel title="Trading permitted?">
        {state.data ? (
          <div className="flex items-center gap-4">
            <span
              className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${
                state.data.trading_permitted
                  ? 'bg-bullish/15 text-bullish border-bullish/30'
                  : 'bg-bearish/15 text-bearish border-bearish/30'
              }`}
            >
              {state.data.trading_permitted ? 'Permitted' : 'Blocked'}
            </span>
            <span className="text-sm text-slate-400">
              {state.data.reason ?? 'No system-level halt is in effect.'}
            </span>
          </div>
        ) : (
          <span className="text-sm text-slate-500">—</span>
        )}
        <p className="mt-3 text-xs text-slate-500">
          This only reflects system-level halts (engine state). Per-trade rules
          (spread, sizing, cooldown) need a concrete trade and are not evaluated here.
        </p>
      </Panel>

      <Panel title="Active limits">
        {params ? (
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Max risk per trade" value={formatPercent(params.max_risk_per_trade)} />
            <Metric label="Max position size" value={formatPercent(params.max_position_size)} />
            <Metric label="Max asset exposure" value={formatPercent(params.max_asset_exposure)} />
            <Metric
              label="Max portfolio exposure"
              value={formatPercent(params.max_portfolio_exposure)}
            />
            <Metric
              label="Max simultaneous positions"
              value={String(params.max_simultaneous_positions)}
            />
            <Metric label="Max daily loss" value={formatPercent(params.max_daily_loss)} />
            <Metric label="Max drawdown" value={formatPercent(params.max_drawdown)} />
            <Metric
              label="Max consecutive losses"
              value={String(params.max_consecutive_losses)}
            />
            <Metric label="Max slippage" value={formatPercent(params.max_slippage)} />
            <Metric label="Spread protection" value={formatPercent(params.spread_protection)} />
            <Metric
              label="Volatility protection"
              value={formatPercent(params.volatility_protection)}
            />
            <Metric
              label="Stale data protection"
              value={`${params.stale_data_protection_seconds}s`}
            />
            <Metric
              label="API failure threshold"
              value={String(params.api_failure_protection_threshold)}
            />
            <Metric
              label="Model health protection"
              value={params.model_health_protection ? 'On' : 'Off'}
            />
            <Metric label="Cooldown period" value={`${params.cooldown_period_seconds}s`} />
          </div>
        ) : (
          <span className="text-sm text-slate-500">—</span>
        )}
      </Panel>

      <Panel title="Decision history">
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">
            No rejections or pauses have been recorded. Every approval is silent by design —
            only a rejection or pause is persisted here (§47).
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Decision</th>
                <th className="pb-2">Rule</th>
                <th className="pb-2">Reason</th>
                <th className="pb-2">When</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((event) => (
                <tr key={event.id} className="border-t border-surface-800">
                  <td className="py-2 text-slate-300">{event.symbol ?? '—'}</td>
                  <td className="py-2">
                    <span
                      className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${
                        DECISION_STYLES[event.decision] ?? DECISION_STYLES.PAUSED
                      }`}
                    >
                      {event.decision}
                    </span>
                  </td>
                  <td className="py-2 font-mono text-[11px] text-slate-400">{event.rule}</td>
                  <td className="py-2 text-slate-400">{event.reason}</td>
                  <td className="py-2 text-slate-500">{formatTimestamp(event.timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
