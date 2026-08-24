import { useMemo, useState } from 'react';

import { Panel } from '@/components/ui/Panel';
import { useEventStream } from '@/hooks/useEventStream';
import type { LogEventData } from '@/types/events';

const LEVELS = ['ALL', 'INFO', 'WARNING', 'ERROR'] as const;

const LEVEL_COLOURS: Record<string, string> = {
  ERROR: 'text-bearish',
  WARNING: 'text-caution',
  INFO: 'text-slate-300',
  DEBUG: 'text-slate-500',
};

export function LogsPage() {
  const { events, status } = useEventStream();
  const [level, setLevel] = useState<(typeof LEVELS)[number]>('ALL');

  const logs = useMemo(
    () =>
      events
        .filter((event) => event.event === 'log_event')
        .filter((event) => level === 'ALL' || (event.data as unknown as LogEventData).level === level),
    [events, level],
  );

  return (
    <Panel
      title="Live logs"
      actions={
        <div className="flex items-center gap-2">
          {LEVELS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setLevel(option)}
              className={`rounded px-2 py-0.5 text-[11px] ${
                level === option
                  ? 'bg-accent/20 text-accent'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      }
    >
      {status !== 'open' ? (
        <p className="mb-3 text-[11px] text-caution">
          WebSocket is {status}; the viewer resumes automatically on reconnect.
        </p>
      ) : null}

      {logs.length === 0 ? (
        <p className="text-sm text-slate-500">
          No log events received yet. Only warnings, errors, and trading/risk/model events are
          streamed to the browser.
        </p>
      ) : (
        <ul className="space-y-1 font-mono text-[12px]">
          {logs.map((event, index) => {
            const data = event.data as unknown as LogEventData;
            return (
              <li key={`${event.timestamp}-${index}`} className="flex gap-3">
                <span className="shrink-0 text-slate-600">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
                <span className={`w-16 shrink-0 ${LEVEL_COLOURS[data.level] ?? 'text-slate-400'}`}>
                  {data.level}
                </span>
                <span className="w-40 shrink-0 truncate text-slate-500">{data.component}</span>
                <span className="text-slate-300">{data.message}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
