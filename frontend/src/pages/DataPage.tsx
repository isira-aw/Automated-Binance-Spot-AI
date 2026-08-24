import { useState } from 'react';

import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Metric } from '@/components/ui/Metric';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import { apiPost } from '@/lib/api';
import type { BackfillJobResponse, CoverageEntry, IntegrityReportEntry } from '@/types/api';

function formatTimestamp(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

/**
 * Historical data coverage, backfill and integrity controls (§17, §67 phase 6).
 *
 * Reads what has actually been persisted -- there is no synthetic or
 * estimated data shown here (§96).
 */
export function DataPage() {
  const coverage = useApi<CoverageEntry[]>('/market/coverage', 10_000);
  const job = useApi<BackfillJobResponse | null>('/market/backfill/status', 3_000);
  const [starting, setStarting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [validation, setValidation] = useState<IntegrityReportEntry[] | null>(null);

  if (coverage.error) return <ErrorNotice error={coverage.error} />;

  const rows = coverage.data ?? [];
  const totalCandles = rows.reduce((sum, row) => sum + row.candle_count, 0);
  const jobRunning = job.data?.running ?? false;

  async function startBackfill() {
    setActionError(null);
    setStarting(true);
    try {
      await apiPost('/market/backfill');
      job.refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Failed to start backfill.');
    } finally {
      setStarting(false);
    }
  }

  async function runIntegrityCheck() {
    setActionError(null);
    setValidating(true);
    try {
      const reports = await apiPost<IntegrityReportEntry[]>('/market/integrity/validate');
      setValidation(reports);
      coverage.refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Integrity check failed.');
    } finally {
      setValidating(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Panel title="Stored candles">
          <Metric label="Total closed candles" value={totalCandles.toLocaleString()} />
        </Panel>
        <Panel title="Coverage">
          <Metric label="Symbol / timeframe pairs" value={String(rows.length)} />
        </Panel>
        <Panel title="Backfill">
          <Metric label="Status" value={jobRunning ? 'Running' : 'Idle'} />
        </Panel>
      </div>

      <Panel
        title="Historical data coverage"
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void runIntegrityCheck()}
              disabled={validating}
              className="rounded border border-surface-600 px-3 py-1 text-xs text-slate-300 hover:bg-surface-800 disabled:opacity-50"
            >
              {validating ? 'Checking…' : 'Run integrity check'}
            </button>
            <button
              type="button"
              onClick={() => void startBackfill()}
              disabled={starting || jobRunning}
              className="rounded border border-bullish/40 bg-bullish/10 px-3 py-1 text-xs text-bullish hover:bg-bullish/20 disabled:opacity-50"
            >
              {jobRunning ? 'Backfill running…' : starting ? 'Starting…' : 'Start backfill'}
            </button>
          </div>
        }
      >
        {actionError ? (
          <div className="mb-3 rounded border border-bearish/40 bg-bearish/10 p-2 text-xs text-bearish">
            {actionError}
          </div>
        ) : null}

        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">
            No history has been ingested yet. Use "Start backfill" to download the maximum
            available history for each configured symbol and timeframe (§17).
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Timeframe</th>
                <th className="pb-2">Candles</th>
                <th className="pb-2">Missing</th>
                <th className="pb-2">First</th>
                <th className="pb-2">Last</th>
                <th className="pb-2">Last checked</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.symbol}-${row.timeframe}`} className="border-t border-surface-800">
                  <td className="py-2 text-slate-300">{row.symbol}</td>
                  <td className="py-2 text-slate-300">{row.timeframe}</td>
                  <td className="py-2 text-slate-400">{row.candle_count.toLocaleString()}</td>
                  <td className={`py-2 ${row.missing_candles > 0 ? 'text-caution' : 'text-slate-500'}`}>
                    {row.missing_candles}
                  </td>
                  <td className="py-2 text-slate-500">{formatTimestamp(row.first_candle_open)}</td>
                  <td className="py-2 text-slate-500">{formatTimestamp(row.last_candle_open)}</td>
                  <td className="py-2 text-slate-500">{formatTimestamp(row.last_integrity_check)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {job.data && job.data.results.length > 0 ? (
        <Panel title="Last backfill run">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Timeframe</th>
                <th className="pb-2">Inserted</th>
                <th className="pb-2">Pages</th>
                <th className="pb-2">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {job.data.results.map((result) => (
                <tr key={`${result.symbol}-${result.timeframe}`} className="border-t border-surface-800">
                  <td className="py-2 text-slate-300">{result.symbol}</td>
                  <td className="py-2 text-slate-300">{result.timeframe}</td>
                  <td className="py-2 text-slate-400">{result.candles_inserted.toLocaleString()}</td>
                  <td className="py-2 text-slate-400">{result.pages_fetched}</td>
                  <td className={`py-2 ${result.error ? 'text-bearish' : 'text-slate-500'}`}>
                    {result.error ?? result.stopped_reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {job.data.error ? (
            <div className="mt-3 rounded border border-bearish/40 bg-bearish/10 p-2 text-xs text-bearish">
              Job failed before completing: {job.data.error}
            </div>
          ) : null}
        </Panel>
      ) : null}

      {validation ? (
        <Panel title="Integrity report">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Timeframe</th>
                <th className="pb-2">Candles</th>
                <th className="pb-2">Missing</th>
                <th className="pb-2">Clean</th>
              </tr>
            </thead>
            <tbody>
              {validation.map((report) => (
                <tr key={`${report.symbol}-${report.timeframe}`} className="border-t border-surface-800">
                  <td className="py-2 text-slate-300">{report.symbol}</td>
                  <td className="py-2 text-slate-300">{report.timeframe}</td>
                  <td className="py-2 text-slate-400">{report.candle_count.toLocaleString()}</td>
                  <td className="py-2 text-slate-400">{report.missing_candles}</td>
                  <td className={`py-2 ${report.is_clean ? 'text-bullish' : 'text-bearish'}`}>
                    {report.is_clean ? 'Clean' : 'Issues found'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      ) : null}
    </div>
  );
}
