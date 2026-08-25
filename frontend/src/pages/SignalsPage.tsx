import { useState } from 'react';

import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import { apiPost } from '@/lib/api';
import type { SettingsResponse, SignalAction, SignalOut } from '@/types/api';

const ACTION_STYLES: Record<SignalAction, string> = {
  BUY: 'bg-bullish/15 text-bullish border-bullish/30',
  SELL: 'bg-bearish/15 text-bearish border-bearish/30',
  EXIT: 'bg-caution/15 text-caution border-caution/30',
  WAIT: 'bg-surface-800 text-slate-400 border-surface-600',
  NO_VALID_SETUP: 'bg-surface-800 text-slate-500 border-surface-600',
};

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

function formatScore(value: number): string {
  return value.toFixed(3);
}

/**
 * Fused trading signals: technical + LightGBM (§30, §67 phase 13).
 *
 * Every row -- including WAIT and NO_VALID_SETUP -- is a real persisted
 * decision with its full component breakdown, not a summary (§79, §80).
 */
export function SignalsPage() {
  const settings = useApi<SettingsResponse>('/settings');
  const signals = useApi<SignalOut[]>('/signals?limit=50', 15_000);
  const [symbol, setSymbol] = useState('');
  const [timeframe, setTimeframe] = useState('');
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  const assets = settings.data?.trading.assets ?? [];
  const timeframes = settings.data?.trading.timeframes ?? [];
  const effectiveSymbol = symbol || assets[0] || '';
  const effectiveTimeframe = timeframe || settings.data?.trading.decision_timeframe || timeframes[0] || '';

  if (signals.error) return <ErrorNotice error={signals.error} />;

  async function generate() {
    if (!effectiveSymbol || !effectiveTimeframe) return;
    setGenerateError(null);
    setGenerating(true);
    try {
      await apiPost<SignalOut>('/signals/generate', {
        symbol: effectiveSymbol,
        timeframe: effectiveTimeframe,
      });
      signals.refresh();
    } catch (error) {
      setGenerateError(
        error instanceof Error ? error.message : 'Failed to generate a signal.',
      );
    } finally {
      setGenerating(false);
    }
  }

  const rows = signals.data ?? [];

  return (
    <div className="space-y-6">
      <Panel
        title="Generate a signal"
        actions={
          <div className="flex items-center gap-2">
            <select
              value={effectiveSymbol}
              onChange={(event) => setSymbol(event.target.value)}
              className="rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            >
              {assets.map((asset) => (
                <option key={asset} value={asset}>
                  {asset}
                </option>
              ))}
            </select>
            <select
              value={effectiveTimeframe}
              onChange={(event) => setTimeframe(event.target.value)}
              className="rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            >
              {timeframes.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => void generate()}
              disabled={generating || !effectiveSymbol || !effectiveTimeframe}
              className="rounded border border-accent/40 bg-accent/10 px-3 py-1 text-xs text-accent hover:bg-accent/20 disabled:opacity-50"
            >
              {generating ? 'Generating…' : 'Generate signal'}
            </button>
          </div>
        }
      >
        {generateError ? (
          <div className="mb-3 rounded border border-bearish/40 bg-bearish/10 p-2 text-xs text-bearish">
            {generateError}
          </div>
        ) : null}
        <p className="text-sm text-slate-400">
          Fuses the latest technical features and, if a model is registered, the LightGBM
          baseline into a single decision on the [0, 1] scale. Nothing here places an order —
          the risk engine and execution are not wired to signal generation yet.
        </p>
      </Panel>

      <Panel title="Recent signals">
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">
            No signals have been generated yet. Use "Generate signal" above, once historical
            data and technical features have been computed for a symbol and timeframe.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Timeframe</th>
                <th className="pb-2">Action</th>
                <th className="pb-2">Score</th>
                <th className="pb-2">Confidence</th>
                <th className="pb-2">Generated</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((signal) => (
                <SignalRow
                  key={signal.id}
                  signal={signal}
                  expanded={expanded === signal.id}
                  onToggle={() => setExpanded(expanded === signal.id ? null : signal.id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

function SignalRow({
  signal,
  expanded,
  onToggle,
}: {
  signal: SignalOut;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="border-t border-surface-800">
        <td className="py-2 text-slate-300">{signal.symbol}</td>
        <td className="py-2 text-slate-300">{signal.timeframe}</td>
        <td className="py-2">
          <span
            className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${ACTION_STYLES[signal.action]}`}
          >
            {signal.action.replace(/_/g, ' ')}
          </span>
        </td>
        <td className="py-2 text-slate-400">{formatScore(signal.score)}</td>
        <td className="py-2 text-slate-400">{formatScore(signal.confidence)}</td>
        <td className="py-2 text-slate-500">{formatTimestamp(signal.generated_at)}</td>
        <td className="py-2 text-right">
          <button
            type="button"
            onClick={onToggle}
            className="text-[11px] text-accent hover:underline"
          >
            {expanded ? 'Hide' : 'Details'}
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-t border-surface-800 bg-surface-900/50">
          <td colSpan={7} className="py-3">
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="metric-label mb-1">Reason codes</div>
                <ul className="space-y-0.5 font-mono text-[11px] text-slate-400">
                  {signal.reason_codes.map((code) => (
                    <li key={code}>{code}</li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="metric-label mb-1">Components</div>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500">
                      <th className="pb-1">Kind</th>
                      <th className="pb-1">Score</th>
                      <th className="pb-1">Weight</th>
                      <th className="pb-1">Confidence</th>
                      <th className="pb-1">Active</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signal.components.map((component) => (
                      <tr key={component.kind} className="border-t border-surface-800">
                        <td className="py-1 text-slate-300">{component.kind}</td>
                        <td className="py-1 text-slate-400">{formatScore(component.score)}</td>
                        <td className="py-1 text-slate-400">{formatScore(component.weight)}</td>
                        <td className="py-1 text-slate-400">
                          {component.confidence !== null ? formatScore(component.confidence) : '—'}
                        </td>
                        <td className={`py-1 ${component.active ? 'text-bullish' : 'text-slate-500'}`}>
                          {component.active ? 'Active' : 'Inactive'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
