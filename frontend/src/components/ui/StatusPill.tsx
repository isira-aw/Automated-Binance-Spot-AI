import type { ComponentHealth } from '@/types/api';

const STYLES: Record<ComponentHealth, string> = {
  ONLINE: 'bg-bullish/15 text-bullish border-bullish/30',
  OFFLINE: 'bg-bearish/15 text-bearish border-bearish/30',
  ERROR: 'bg-bearish/15 text-bearish border-bearish/30',
  DEGRADED: 'bg-caution/15 text-caution border-caution/30',
  DISABLED: 'bg-surface-800 text-slate-500 border-surface-600',
  NOT_IMPLEMENTED: 'bg-surface-800 text-slate-500 border-surface-600',
};

const LABELS: Record<ComponentHealth, string> = {
  ONLINE: 'Online',
  OFFLINE: 'Offline',
  ERROR: 'Error',
  DEGRADED: 'Degraded',
  DISABLED: 'Disabled',
  NOT_IMPLEMENTED: 'Not implemented',
};

export function StatusPill({ status }: { status: ComponentHealth }) {
  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium ${STYLES[status]}`}
    >
      {LABELS[status]}
    </span>
  );
}
