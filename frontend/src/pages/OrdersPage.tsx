import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Panel } from '@/components/ui/Panel';
import { useApi } from '@/hooks/useApi';
import type { PaperOrderOut } from '@/types/api';

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

const SIDE_STYLES: Record<string, string> = {
  BUY: 'bg-bullish/15 text-bullish border-bullish/30',
  SELL: 'bg-bearish/15 text-bearish border-bearish/30',
};

/**
 * Paper order history — every filled entry and exit (§11B, §59).
 *
 * Read-only: orders are placed from the Positions page. A rejected attempt
 * never reaches here (there is no order to fill) — see the Risk page's
 * decision history for those.
 */
export function OrdersPage() {
  const orders = useApi<PaperOrderOut[]>('/orders', 15_000);

  if (orders.error) return <ErrorNotice error={orders.error} />;

  const rows = orders.data ?? [];

  return (
    <Panel title="Paper order history">
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500">No paper orders have been filled yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
              <th className="pb-2">Symbol</th>
              <th className="pb-2">Side</th>
              <th className="pb-2">Quantity</th>
              <th className="pb-2">Avg fill price</th>
              <th className="pb-2">Fee</th>
              <th className="pb-2">Submitted</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((order) => (
              <tr key={order.id} className="border-t border-surface-800">
                <td className="py-2 text-slate-300">{order.symbol}</td>
                <td className="py-2">
                  <span
                    className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${
                      SIDE_STYLES[order.side] ?? SIDE_STYLES.BUY
                    }`}
                  >
                    {order.side}
                  </span>
                </td>
                <td className="py-2 text-slate-400">{order.filled_quantity}</td>
                <td className="py-2 text-slate-400">{order.average_fill_price ?? '—'}</td>
                <td className="py-2 text-slate-400">{order.fee.toFixed(6)}</td>
                <td className="py-2 text-slate-500">{formatTimestamp(order.submitted_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
