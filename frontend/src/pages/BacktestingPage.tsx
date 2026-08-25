import { useState } from 'react';

import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Metric } from '@/components/ui/Metric';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import { apiGet, apiPost } from '@/lib/api';
import type { BacktestRunOut, BacktestRunSummaryOut, SettingsResponse } from '@/types/api';

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

function toDatetimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatMetric(value: unknown, kind: 'pct' | 'number' | 'ratio' = 'number'): string {
  if (value === null || value === undefined) return 'undefined';
  const num = Number(value);
  if (kind === 'pct') return `${(num * 100).toFixed(2)}%`;
  if (kind === 'ratio') return num.toFixed(2);
  return num.toFixed(4);
}

const STATUS_STYLES: Record<string, string> = {
  COMPLETED: 'bg-bullish/15 text-bullish border-bullish/30',
  FAILED: 'bg-bearish/15 text-bearish border-bearish/30',
  RUNNING: 'bg-caution/15 text-caution border-caution/30',
};

/**
 * Run and inspect backtests against the Phase 12 engine (§35, §41, §82).
 *
 * A result is never shown without its full metric set and the seven §82
 * audit disclosures -- a result missing those is not a meaningful one.
 */
export function BacktestingPage() {
  const settings = useApi<SettingsResponse>('/settings');
  const runs = useApi<BacktestRunSummaryOut[]>('/backtests', 15_000);
  const [symbol, setSymbol] = useState('');
  const [timeframe, setTimeframe] = useState('');
  const [rangeStart, setRangeStart] = useState(() =>
    toDatetimeLocal(new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)),
  );
  const [rangeEnd, setRangeEnd] = useState(() => toDatetimeLocal(new Date()));
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [selected, setSelected] = useState<BacktestRunOut | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<number | null>(null);

  const assets = settings.data?.trading.assets ?? [];
  const timeframes = settings.data?.trading.timeframes ?? [];
  const effectiveSymbol = symbol || assets[0] || '';
  const effectiveTimeframe = timeframe || settings.data?.trading.decision_timeframe || timeframes[0] || '';

  if (runs.error) return <ErrorNotice error={runs.error} />;

  async function submit() {
    if (!effectiveSymbol || !effectiveTimeframe) return;
    setRunError(null);
    setRunning(true);
    try {
      const result = await apiPost<BacktestRunOut>('/backtests/run', {
        symbol: effectiveSymbol,
        timeframe: effectiveTimeframe,
        range_start: new Date(rangeStart).toISOString(),
        range_end: new Date(rangeEnd).toISOString(),
      });
      setSelected(result);
      runs.refresh();
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Failed to run the backtest.');
    } finally {
      setRunning(false);
    }
  }

  async function viewDetail(id: number) {
    setLoadingDetail(id);
    try {
      const detail = await apiGet<BacktestRunOut>(`/backtests/${id}`);
      setSelected(detail);
    } finally {
      setLoadingDetail(null);
    }
  }

  const rows = runs.data ?? [];
  const metrics = selected?.metrics ?? null;

  return (
    <div className="space-y-6">
      <Panel title="Run a backtest">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-400">
            Symbol
            <select
              value={effectiveSymbol}
              onChange={(event) => setSymbol(event.target.value)}
              className="mt-1 block rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            >
              {assets.map((asset) => (
                <option key={asset} value={asset}>
                  {asset}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            Timeframe
            <select
              value={effectiveTimeframe}
              onChange={(event) => setTimeframe(event.target.value)}
              className="mt-1 block rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            >
              {timeframes.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-400">
            From
            <input
              type="datetime-local"
              value={rangeStart}
              onChange={(event) => setRangeStart(event.target.value)}
              className="mt-1 block rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            />
          </label>
          <label className="text-xs text-slate-400">
            To
            <input
              type="datetime-local"
              value={rangeEnd}
              onChange={(event) => setRangeEnd(event.target.value)}
              className="mt-1 block rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            />
          </label>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={running || !effectiveSymbol || !effectiveTimeframe}
            className="rounded border border-accent/40 bg-accent/10 px-3 py-1 text-xs text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            {running ? 'Running…' : 'Run backtest'}
          </button>
        </div>
        {runError ? (
          <div className="mt-3 rounded border border-bearish/40 bg-bearish/10 p-2 text-xs text-bearish">
            {runError}
          </div>
        ) : null}
        <p className="mt-3 text-sm text-slate-400">
          Uses a technical-only reference strategy (ATR-based stop/target) against persisted
          candles and features — the same risk engine, position sizing, and fill model paper
          trading uses. Requires historical candles and technical features to already exist for
          the chosen symbol, timeframe, and range.
        </p>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Recent runs">
          {rows.length === 0 ? (
            <p className="text-sm text-slate-500">No backtests have been run yet.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                  <th className="pb-2">Symbol</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Net P&L</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {rows.map((run) => (
                  <tr key={run.id} className="border-t border-surface-800">
                    <td className="py-2 text-slate-300">
                      {run.symbols.join(', ')} · {run.timeframe}
                    </td>
                    <td className="py-2">
                      <span
                        className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${
                          STATUS_STYLES[run.status] ?? STATUS_STYLES.RUNNING
                        }`}
                      >
                        {run.status}
                      </span>
                    </td>
                    <td className="py-2 text-slate-400">
                      {run.metrics?.net_pnl !== undefined && run.metrics?.net_pnl !== null
                        ? Number(run.metrics.net_pnl).toFixed(4)
                        : '—'}
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => void viewDetail(run.id)}
                        className="text-[11px] text-accent hover:underline"
                      >
                        {loadingDetail === run.id ? 'Loading…' : 'View'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel title={selected ? `Run ${selected.job_id.slice(0, 8)}` : 'Result'}>
          {!selected ? (
            <p className="text-sm text-slate-500">Run a backtest or select one from the list.</p>
          ) : selected.status === 'FAILED' ? (
            <p className="text-sm text-bearish">{selected.error}</p>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <Metric label="Trades" value={String(metrics?.trade_count ?? 0)} />
                <Metric
                  label="Win rate"
                  value={metrics?.win_rate != null ? formatMetric(metrics.win_rate, 'pct') : 'undefined'}
                />
                <Metric label="Net P&L" value={formatMetric(metrics?.net_pnl)} />
                <Metric label="Profit factor" value={formatMetric(metrics?.profit_factor, 'ratio')} />
                <Metric label="Expectancy" value={formatMetric(metrics?.expectancy)} />
                <Metric
                  label="Max drawdown"
                  value={metrics?.max_drawdown != null ? formatMetric(metrics.max_drawdown, 'pct') : 'undefined'}
                />
                <Metric label="Sharpe" value={formatMetric(metrics?.sharpe_ratio, 'ratio')} />
                <Metric label="Sortino" value={formatMetric(metrics?.sortino_ratio, 'ratio')} />
                <Metric label="Total fees" value={formatMetric(metrics?.total_fees)} />
              </div>

              <div>
                <div className="metric-label mb-1">Audit disclosures (§82)</div>
                <dl className="space-y-1.5 text-xs text-slate-400">
                  {selected.assumptions
                    ? Object.entries(selected.assumptions).map(([key, value]) => (
                        <div key={key}>
                          <dt className="font-mono text-slate-500">{key}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))
                    : null}
                </dl>
              </div>

              <div>
                <div className="metric-label mb-1">Trades ({selected.trades.length})</div>
                {selected.trades.length === 0 ? (
                  <p className="text-xs text-slate-500">No trades were taken during this run.</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                        <th className="pb-1">Entry</th>
                        <th className="pb-1">Exit</th>
                        <th className="pb-1">Net P&L</th>
                        <th className="pb-1">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selected.trades.map((trade, index) => (
                        <tr key={index} className="border-t border-surface-800">
                          <td className="py-1 text-slate-400">{formatTimestamp(trade.entry_time)}</td>
                          <td className="py-1 text-slate-400">{formatTimestamp(trade.exit_time)}</td>
                          <td
                            className={`py-1 ${trade.net_pnl >= 0 ? 'text-bullish' : 'text-bearish'}`}
                          >
                            {trade.net_pnl.toFixed(4)}
                          </td>
                          <td className="py-1 text-slate-500">{trade.exit_reason ?? '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
