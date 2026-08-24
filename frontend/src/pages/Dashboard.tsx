import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Metric } from '@/components/ui/Metric';
import { Panel } from '@/components/ui/Panel';
import { StatusPill } from '@/components/ui/StatusPill';
import { useApi } from '@/hooks/useApi';
import { useEventStream } from '@/hooks/useEventStream';
import type { HealthResponse, SettingsResponse, SystemStateResponse } from '@/types/api';

export function Dashboard() {
  const health = useApi<HealthResponse>('/system/health', 10_000);
  const state = useApi<SystemStateResponse>('/system/state', 10_000);
  const settings = useApi<SettingsResponse>('/settings');
  const { status, events } = useEventStream();

  if (health.error) return <ErrorNotice error={health.error} />;

  const tiers = settings.data?.tiers;
  const influencing = tiers?.influencing_signals ?? [];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Panel title="Mode">
          <Metric
            label="Trading mode"
            value={state.data?.mode ?? '—'}
            hint={state.data?.live_trading_enabled ? 'Live enabled' : 'Live trading disabled'}
          />
        </Panel>
        <Panel title="Engine">
          <Metric
            label="Engine state"
            value={state.data?.engine_state ?? '—'}
            hint="Trading engine is not built yet (Tier 1 phase list)"
          />
        </Panel>
        <Panel title="System">
          <div className="flex items-center gap-2">
            {health.data ? <StatusPill status={health.data.overall} /> : <span>—</span>}
          </div>
          <div className="mt-2 text-[11px] text-slate-500">
            checked {health.data ? new Date(health.data.checked_at).toLocaleTimeString() : '—'}
          </div>
        </Panel>
        <Panel title="Live stream">
          <Metric label="WebSocket" value={status} hint={`${events.length} buffered events`} />
        </Panel>
      </div>

      <Panel title="Components">
        <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(health.data?.components ?? {}).map(([name, component]) => (
            <div key={name} className="flex items-center justify-between border-b border-surface-800 py-1.5">
              <span className="text-sm text-slate-300">{name.replace(/_/g, ' ')}</span>
              <StatusPill status={component.status} />
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="What is influencing decisions">
        {influencing.length === 0 ? (
          <p className="text-sm text-slate-400">
            No component currently influences trading decisions. Signal fusion is not implemented
            yet, so the platform produces no signals and places no orders — paper or otherwise.
          </p>
        ) : (
          <ul className="text-sm text-slate-300">
            {influencing.map((component) => (
              <li key={component}>{component}</li>
            ))}
          </ul>
        )}
        {tiers ? (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <TierList label="Tier 1 — core" items={tiers.tier1_components} enabled={null} />
            <TierList
              label="Tier 2 — shadow / research"
              items={tiers.tier2_components}
              enabled={tiers.tier2_enabled}
            />
          </div>
        ) : null}
      </Panel>

      <Panel title="Account">
        <p className="text-sm text-slate-400">
          Account and equity figures are shown once the paper trading simulator is implemented.
          The target account size is under $50, so most signals are expected to be rejected as
          <span className="font-mono text-slate-300"> TRADE_NOT_ECONOMIC</span> — that is the
          normal outcome at this size, not a failure.
        </p>
      </Panel>
    </div>
  );
}

function TierList({
  label,
  items,
  enabled,
}: {
  label: string;
  items: string[];
  enabled: Record<string, boolean> | null;
}) {
  return (
    <div>
      <div className="metric-label mb-1">{label}</div>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item} className="flex items-center justify-between text-sm text-slate-300">
            <span>{item.replace(/_/g, ' ')}</span>
            <span className="text-[11px] text-slate-500">
              {enabled ? (enabled[item] ? 'enabled' : 'disabled') : 'planned'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
