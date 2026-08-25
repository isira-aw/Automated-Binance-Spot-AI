import { useState } from 'react';

import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import { apiPost } from '@/lib/api';
import type { OpenOrderRequest, PaperPositionOut, SettingsResponse } from '@/types/api';

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

/**
 * Open paper positions, and placing/closing a paper trade manually (§11B, §31).
 *
 * Manual only: nothing here is triggered automatically by a generated
 * signal. Every entry still goes through the risk engine -- a rejection
 * shows the engine's reason rather than silently doing nothing.
 */
export function PositionsPage() {
  const settings = useApi<SettingsResponse>('/settings');
  const positions = useApi<PaperPositionOut[]>('/positions', 10_000);
  const [symbol, setSymbol] = useState('');
  const [stopPrice, setStopPrice] = useState('');
  const [takeProfit, setTakeProfit] = useState('');
  const [placing, setPlacing] = useState(false);
  const [placeError, setPlaceError] = useState<string | null>(null);
  const [closingSymbol, setClosingSymbol] = useState<string | null>(null);

  const assets = settings.data?.trading.assets ?? [];
  const effectiveSymbol = symbol || assets[0] || '';

  if (positions.error) return <ErrorNotice error={positions.error} />;

  async function placeOrder() {
    if (!effectiveSymbol || !stopPrice) return;
    setPlaceError(null);
    setPlacing(true);
    try {
      const body: OpenOrderRequest = {
        symbol: effectiveSymbol,
        stop_price: Number(stopPrice),
        ...(takeProfit ? { take_profit: Number(takeProfit) } : {}),
      };
      await apiPost('/orders', body);
      setStopPrice('');
      setTakeProfit('');
      positions.refresh();
    } catch (error) {
      setPlaceError(error instanceof Error ? error.message : 'Failed to place the order.');
    } finally {
      setPlacing(false);
    }
  }

  async function closePosition(positionSymbol: string) {
    setClosingSymbol(positionSymbol);
    try {
      await apiPost(`/positions/${positionSymbol}/close`);
      positions.refresh();
    } finally {
      setClosingSymbol(null);
    }
  }

  const rows = positions.data ?? [];

  return (
    <div className="space-y-6">
      <Panel title="Place a paper trade">
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
            Stop price
            <input
              type="number"
              step="any"
              value={stopPrice}
              onChange={(event) => setStopPrice(event.target.value)}
              placeholder="required"
              className="mt-1 block w-28 rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            />
          </label>
          <label className="text-xs text-slate-400">
            Take profit
            <input
              type="number"
              step="any"
              value={takeProfit}
              onChange={(event) => setTakeProfit(event.target.value)}
              placeholder="optional"
              className="mt-1 block w-28 rounded border border-surface-600 bg-surface-900 px-2 py-1 text-xs text-slate-300"
            />
          </label>
          <button
            type="button"
            onClick={() => void placeOrder()}
            disabled={placing || !effectiveSymbol || !stopPrice}
            className="rounded border border-accent/40 bg-accent/10 px-3 py-1 text-xs text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            {placing ? 'Placing…' : 'Place order'}
          </button>
        </div>
        {placeError ? (
          <div
            data-testid="place-order-error"
            className="mt-3 rounded border border-bearish/40 bg-bearish/10 p-2 text-xs text-bearish"
          >
            {placeError}
          </div>
        ) : null}
        <p className="mt-3 text-sm text-slate-400">
          A market buy at the current reference price, sized by the risk engine from your stop
          distance. A stop is required — position sizing has no meaning without one. Rejections
          (risk limits, cooldown, an already-open position) are recorded and shown above, not
          silently ignored.
        </p>
      </Panel>

      <Panel title="Open positions">
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">No open paper positions.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Quantity</th>
                <th className="pb-2">Entry</th>
                <th className="pb-2">Stop</th>
                <th className="pb-2">Take profit</th>
                <th className="pb-2">Opened</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((position) => (
                <tr key={position.id} className="border-t border-surface-800">
                  <td className="py-2 text-slate-300">{position.symbol}</td>
                  <td className="py-2 text-slate-400">{position.quantity}</td>
                  <td className="py-2 text-slate-400">{position.entry_price}</td>
                  <td className="py-2 text-slate-400">{position.stop_loss ?? '—'}</td>
                  <td className="py-2 text-slate-400">{position.take_profit ?? '—'}</td>
                  <td className="py-2 text-slate-500">{formatTimestamp(position.entry_time)}</td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      onClick={() => void closePosition(position.symbol)}
                      disabled={closingSymbol === position.symbol}
                      className="text-[11px] text-bearish hover:underline disabled:opacity-50"
                    >
                      {closingSymbol === position.symbol ? 'Closing…' : 'Close'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
