import { NavLink, Outlet } from 'react-router-dom';

import { useApi } from '@/hooks/useApi';
import { useEventStream } from '@/hooks/useEventStream';
import type { SystemStateResponse, VersionResponse } from '@/types/api';

const TIER1_PAGES = [
  ['/', 'Dashboard'],
  ['/market', 'Market'],
  ['/signals', 'Signals'],
  ['/positions', 'Positions'],
  ['/orders', 'Orders'],
  ['/trades', 'Trades'],
  ['/backtesting', 'Backtesting'],
  ['/risk', 'Risk'],
  ['/data', 'Data'],
  ['/system', 'System'],
  ['/settings', 'Settings'],
  ['/logs', 'Logs'],
] as const;

const TIER2_PAGES = [
  ['/models', 'Models'],
  ['/training', 'Training'],
  ['/patterns', 'Patterns'],
  ['/news', 'News'],
  ['/fundamentals', 'Fundamentals'],
] as const;

const MODE_STYLES: Record<string, string> = {
  PAPER: 'bg-accent/15 text-accent border-accent/40',
  BACKTEST: 'bg-surface-800 text-slate-300 border-surface-600',
  BINANCE_TESTNET: 'bg-caution/15 text-caution border-caution/40',
  LIVE: 'bg-bearish/20 text-bearish border-bearish/50',
};

export function AppShell() {
  const { status, lastHeartbeat } = useEventStream();
  const version = useApi<VersionResponse>('/system/version', 30_000);
  const state = useApi<SystemStateResponse>('/system/state', 10_000);

  const mode = state.data?.mode ?? 'PAPER';

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-surface-800 bg-surface-900">
        <div className="border-b border-surface-800 px-4 py-4">
          <div className="text-sm font-semibold text-slate-100">Binance Spot AI</div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            {version.data?.environment ?? '—'} · strategy {version.data?.strategy_version ?? '—'}
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto py-3">
          <SectionLabel>Tier 1 — core</SectionLabel>
          {TIER1_PAGES.map(([path, label]) => (
            <NavItem key={path} to={path} label={label} />
          ))}
          <SectionLabel>Tier 2 — intelligence layer</SectionLabel>
          {TIER2_PAGES.map(([path, label]) => (
            <NavItem key={path} to={path} label={label} />
          ))}
        </nav>

        <div className="border-t border-surface-800 px-4 py-3 text-[11px] text-slate-500">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${
                status === 'open'
                  ? 'bg-bullish'
                  : status === 'connecting'
                    ? 'bg-caution'
                    : 'bg-bearish'
              }`}
            />
            <span>WebSocket {status}</span>
          </div>
          {lastHeartbeat ? (
            <div className="mt-1">last heartbeat {new Date(lastHeartbeat).toLocaleTimeString()}</div>
          ) : null}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-surface-800 bg-surface-900 px-6 py-3">
          <div className="flex items-center gap-3">
            <span
              className={`rounded border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${
                MODE_STYLES[mode] ?? MODE_STYLES.PAPER
              }`}
            >
              {mode === 'PAPER' ? 'Paper trading' : mode.replace('_', ' ')}
            </span>
            {mode !== 'LIVE' ? (
              <span className="text-[11px] text-slate-500">No real funds are at risk.</span>
            ) : null}
          </div>
          <div className="text-[11px] text-slate-500">
            engine: {state.data?.engine_state ?? '—'} · live trading{' '}
            {state.data?.live_trading_enabled ? 'enabled' : 'disabled'}
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: string }) {
  return (
    <div className="px-4 pb-1 pt-3 text-[10px] uppercase tracking-widest text-slate-600">
      {children}
    </div>
  );
}

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `block px-4 py-1.5 text-sm transition-colors ${
          isActive
            ? 'border-l-2 border-accent bg-surface-850 text-slate-100'
            : 'border-l-2 border-transparent text-slate-400 hover:bg-surface-850 hover:text-slate-200'
        }`
      }
    >
      {label}
    </NavLink>
  );
}
