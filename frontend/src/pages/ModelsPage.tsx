import { useState } from 'react';

import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import { apiPost } from '@/lib/api';
import type {
  ModelStatus,
  ModelVersionOut,
  SettingsResponse,
  TrainingOutcomeOut,
  TrainingStatusOut,
} from '@/types/api';

const STATUS_STYLES: Record<ModelStatus, string> = {
  CANDIDATE: 'bg-surface-800 text-slate-400 border-surface-600',
  VALIDATED: 'bg-accent/15 text-accent border-accent/30',
  PRODUCTION: 'bg-bullish/15 text-bullish border-bullish/30',
  ARCHIVED: 'bg-surface-800 text-slate-500 border-surface-600',
  REJECTED: 'bg-bearish/15 text-bearish border-bearish/30',
};

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

/**
 * The LightGBM model registry: trigger training, inspect what got registered
 * (§39, §67 phase 9). Every version shown here came from a real training run
 * against persisted data -- there is no synthetic metric on this page.
 */
export function ModelsPage() {
  const settings = useApi<SettingsResponse>('/settings');
  const models = useApi<ModelVersionOut[]>('/models', 10_000);
  const trainStatus = useApi<TrainingStatusOut>('/models/train/status', 5_000);
  const [symbol, setSymbol] = useState('');
  const [timeframe, setTimeframe] = useState('');
  const [starting, setStarting] = useState(false);
  const [trainError, setTrainError] = useState<string | null>(null);

  const assets = settings.data?.trading.assets ?? [];
  const timeframes = settings.data?.trading.timeframes ?? [];
  const effectiveSymbol = symbol || assets[0] || '';
  const effectiveTimeframe = timeframe || settings.data?.trading.decision_timeframe || timeframes[0] || '';

  if (models.error) return <ErrorNotice error={models.error} />;

  const running = trainStatus.data?.running ?? false;
  const rows = models.data ?? [];

  async function startTraining() {
    if (!effectiveSymbol || !effectiveTimeframe) return;
    setTrainError(null);
    setStarting(true);
    try {
      await apiPost<TrainingOutcomeOut>('/models/train', {
        symbol: effectiveSymbol,
        timeframe: effectiveTimeframe,
      });
      trainStatus.refresh();
      models.refresh();
    } catch (error) {
      setTrainError(error instanceof Error ? error.message : 'Failed to start training.');
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="space-y-6">
      <Panel
        title="Train a LightGBM baseline"
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
              onClick={() => void startTraining()}
              disabled={starting || running || !effectiveSymbol || !effectiveTimeframe}
              className="rounded border border-accent/40 bg-accent/10 px-3 py-1 text-xs text-accent hover:bg-accent/20 disabled:opacity-50"
            >
              {running ? 'Training running…' : starting ? 'Starting…' : 'Start training'}
            </button>
          </div>
        }
      >
        {trainError ? (
          <div className="mb-3 rounded border border-bearish/40 bg-bearish/10 p-2 text-xs text-bearish">
            {trainError}
          </div>
        ) : null}
        <p className="text-sm text-slate-400">
          Trains against persisted candles and computed features with a chronological
          train/validation/test split — never a random shuffle, which would leak future bars
          into training. A model that does not clear the minimum validation accuracy or macro
          F1 is registered as <span className="font-mono text-slate-300">REJECTED</span>, not
          silently discarded.
        </p>
        {trainStatus.data?.outcome ? (
          <div className="mt-3 rounded border border-surface-700 bg-surface-900/50 p-3 text-xs text-slate-400">
            Last run: job {trainStatus.data.outcome.job_id} — {trainStatus.data.outcome.status}
            {trainStatus.data.outcome.error ? ` — ${trainStatus.data.outcome.error}` : ''}
          </div>
        ) : null}
      </Panel>

      <Panel title="Model registry">
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">
            No model versions have been trained yet. Every prediction from a registered model
            runs in shadow mode — it is recorded but never influences a trade until promoted
            through backtesting.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Timeframe</th>
                <th className="pb-2">Version</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">Feature version</th>
                <th className="pb-2">Trained</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((model) => (
                <tr key={`${model.model_id}-${model.version}`} className="border-t border-surface-800">
                  <td className="py-2 text-slate-300">{model.symbol ?? '—'}</td>
                  <td className="py-2 text-slate-300">{model.timeframe ?? '—'}</td>
                  <td className="py-2 font-mono text-[11px] text-slate-400">{model.version}</td>
                  <td className="py-2">
                    <span
                      className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLES[model.status]}`}
                    >
                      {model.status}
                    </span>
                  </td>
                  <td className="py-2 text-slate-500">{model.feature_version}</td>
                  <td className="py-2 text-slate-500">{formatTimestamp(model.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
