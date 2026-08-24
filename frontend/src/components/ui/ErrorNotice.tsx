import type { ApiError } from '@/lib/api';

/** Surfaces the backend's error code and message verbatim (§101). */
export function ErrorNotice({ error }: { error: ApiError }) {
  return (
    <div className="rounded border border-bearish/40 bg-bearish/10 p-4 text-sm">
      <div className="font-semibold text-bearish">Request failed</div>
      <div className="mt-1 text-slate-300">Reason: {error.message}</div>
      <div className="mt-1 font-mono text-[11px] text-slate-500">code: {error.code}</div>
    </div>
  );
}
