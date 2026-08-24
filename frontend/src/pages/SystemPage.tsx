import { ErrorNotice } from '@/components/ui/ErrorNotice';
import { Metric } from '@/components/ui/Metric';
import { Panel } from '@/components/ui/Panel';
import { StatusPill } from '@/components/ui/StatusPill';
import { useApi } from '@/hooks/useApi';
import type { HealthResponse, SystemStateResponse, VersionResponse } from '@/types/api';

export function SystemPage() {
  const health = useApi<HealthResponse>('/system/health', 5_000);
  const version = useApi<VersionResponse>('/system/version', 30_000);
  const state = useApi<SystemStateResponse>('/system/state', 10_000);

  if (health.error) return <ErrorNotice error={health.error} />;

  const registryProblems = state.data?.model_registry_problems ?? [];

  return (
    <div className="space-y-6">
      <Panel title="Component health">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500">
              <th className="pb-2">Component</th>
              <th className="pb-2">Status</th>
              <th className="pb-2">Detail</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(health.data?.components ?? {}).map(([name, component]) => (
              <tr key={name} className="border-t border-surface-800">
                <td className="py-2 text-slate-300">{name.replace(/_/g, ' ')}</td>
                <td className="py-2">
                  <StatusPill status={component.status} />
                </td>
                <td className="py-2 text-slate-500">{component.detail ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {registryProblems.length > 0 ? (
        <div className="rounded border border-bearish/40 bg-bearish/10 p-4 text-sm">
          <div className="font-semibold text-bearish">Model registry integrity problem</div>
          <p className="mt-1 text-slate-300">
            The registry references model artifacts that are missing or corrupted on disk. Those
            models cannot be loaded and will not be traded on.
          </p>
          <ul className="mt-2 space-y-1 font-mono text-[11px] text-slate-400">
            {registryProblems.map((problem, index) => (
              <li key={index}>
                {problem.model_id}:{problem.version} ({problem.status}) — {problem.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <Panel title="Version">
          <Metric label="Environment" value={version.data?.environment ?? '—'} />
        </Panel>
        <Panel title="Schema">
          <Metric label="Migration revision" value={version.data?.schema_revision ?? 'not migrated'} />
        </Panel>
        <Panel title="Strategy">
          <Metric label="Strategy version" value={version.data?.strategy_version ?? '—'} />
        </Panel>
        <Panel title="Features">
          <Metric label="Feature version" value={version.data?.feature_version ?? '—'} />
        </Panel>
      </div>

      <Panel title="Persisted state">
        <div className="grid gap-4 sm:grid-cols-4">
          <Metric label="Mode" value={state.data?.mode ?? '—'} />
          <Metric label="Engine" value={state.data?.engine_state ?? '—'} />
          <Metric label="Live armed" value={state.data?.live_armed ? 'yes' : 'no'} />
          <Metric
            label="Last clean shutdown"
            value={
              state.data?.last_shutdown_at
                ? new Date(state.data.last_shutdown_at).toLocaleString()
                : '—'
            }
          />
        </div>
      </Panel>
    </div>
  );
}
