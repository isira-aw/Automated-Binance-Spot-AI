import { NotImplemented } from '@/components/ui/NotImplemented';

/**
 * Pages whose engines are not built yet (§96).  Each states its tier and the
 * phase that will implement it, and shows no data of any kind.
 */
export const PENDING_PAGES = {
  market: { page: 'Market', tier: 'TIER 1', phase: 'Phase 5–6 — Binance market data and history' },
  positions: {
    page: 'Positions',
    tier: 'TIER 1',
    phase: 'Phase 15b — paper trading execution API (order placement, not just simulation)',
  },
  orders: {
    page: 'Orders',
    tier: 'TIER 1',
    phase: 'Phase 15b — paper trading execution API (order placement, not just simulation)',
  },
  trades: {
    page: 'Trades',
    tier: 'TIER 1',
    phase: 'Phase 15b — paper trading execution API (order placement, not just simulation)',
  },
  training: { page: 'Training', tier: 'TIER 2', phase: 'Phase 28 — model registry and retraining' },
  patterns: { page: 'Patterns', tier: 'TIER 2', phase: 'Phase 21 — pattern engine' },
  news: { page: 'News', tier: 'TIER 2', phase: 'Phase 25 — news/fundamental engine' },
  fundamentals: { page: 'Fundamentals', tier: 'TIER 2', phase: 'Phase 25 — news/fundamental engine' },
} as const satisfies Record<string, { page: string; tier: 'TIER 1' | 'TIER 2'; phase: string }>;

export type PendingPageKey = keyof typeof PENDING_PAGES;

export function PendingPage({ name }: { name: PendingPageKey }) {
  const config = PENDING_PAGES[name];
  return <NotImplemented page={config.page} tier={config.tier} phase={config.phase} />;
}
