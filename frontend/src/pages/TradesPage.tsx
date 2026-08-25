import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import type { TradeOut } from '@/types/api';

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

/**
 * The closed paper-trading ledger (§41, §59) — the same metric definitions
 * a backtest uses, computed here from real closed round-trips.
 */
export function TradesPage() {
  const trades = useApi<TradeOut[]>('/trades?venue=PAPER', 15_000);

  if (trades.error) return <ErrorNotice error={trades.error} />;

  const rows = trades.data ?? [];

  return (
    <Panel title="Closed trades">
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">No paper trades have closed yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
              <th className="pb-2">Symbol</th>
              <th className="pb-2">Entry</th>
              <th className="pb-2">Exit</th>
              <th className="pb-2">Net P&L</th>
              <th className="pb-2">Return</th>
              <th className="pb-2">Reason</th>
              <th className="pb-2">Closed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((trade) => (
              <tr key={trade.id} className="border-t border-surface-800">
                <td className="py-2 text-slate-300">{trade.symbol}</td>
                <td className="py-2 text-slate-400">{trade.entry_price}</td>
                <td className="py-2 text-slate-400">{trade.exit_price}</td>
                <td className={`py-2 ${trade.net_pnl >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                  {trade.net_pnl.toFixed(4)}
                </td>
                <td className={`py-2 ${trade.return_pct >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                  {(trade.return_pct * 100).toFixed(2)}%
                </td>
                <td className="py-2 text-slate-500">{trade.exit_reason ?? '—'}</td>
                <td className="py-2 text-slate-500">{formatTimestamp(trade.exit_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
