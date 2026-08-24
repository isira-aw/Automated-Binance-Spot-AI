/**
 * Placeholder for a page whose engine is not built yet (§96).
 *
 * It states plainly that nothing is implemented — it never renders sample
 * numbers, mock charts, or randomized output that could be mistaken for data.
 */
export function NotImplemented({
  page,
  tier,
  phase,
}: {
  page: string;
  tier: 'TIER 1' | 'TIER 2';
  phase: string;
}) {
  return (
    <div className="panel p-8">
      <div className="mb-2 inline-flex items-center gap-2">
        <span className="rounded border border-surface-600 bg-surface-800 px-2 py-0.5 text-[11px] uppercase tracking-wider text-slate-400">
          Not implemented
        </span>
        <span className="rounded border border-surface-600 bg-surface-800 px-2 py-0.5 text-[11px] uppercase tracking-wider text-slate-400">
          {tier}
        </span>
      </div>
      <h2 className="text-lg font-semibold text-slate-200">{page}</h2>
      <p className="mt-2 max-w-2xl text-sm text-slate-400">
        This page has no engine behind it yet. It is scheduled for{' '}
        <span className="text-slate-300">{phase}</span>. Nothing is displayed here rather than
        showing placeholder data that could be mistaken for real market, model, or trading
        activity.
      </p>
    </div>
  );
}
