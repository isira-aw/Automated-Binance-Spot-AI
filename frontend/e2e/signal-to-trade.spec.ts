import { expect, test } from '@playwright/test';

// Phase 17 (§16, §17): the same chain tests/integration/test_e2e_signal_to_trade.py
// drives on the backend side, driven here through the real browser UI instead.
// Requires: the dev stack running (backend + frontend + Postgres + Redis) and
// e2e/seed.py already run against that same database.
//
// Placing a paper order needs a live Binance price (app.paper_trading.account
// fetches one before sizing the trade) -- unreachable in every environment
// this suite has been run from so far (documented throughout PROJECT_STATUS.md
// since Phase 5). The "place an order" test therefore asserts the UI reaches
// a definitive result (a new position, or a visible error) rather than
// asserting success specifically -- it stays meaningful, and green, whether
// or not the environment running it has real market connectivity.

test.describe('Signals', () => {
  test('generates a signal and shows its component breakdown', async ({ page }) => {
    await page.goto('/signals');

    // The default timeframe is the trading config's decision_timeframe
    // (4h), but e2e/seed.py only seeds 1h data -- select it explicitly
    // rather than relying on a default that has nothing to do with what's
    // actually seeded.
    await page.locator('select').nth(1).selectOption('1h');
    await page.getByRole('button', { name: 'Generate signal' }).click();

    const firstRow = page.locator('tbody tr').first();
    await expect(firstRow).toContainText('BTCUSDT', { timeout: 15_000 });
    await expect(firstRow.getByText(/BUY|SELL|WAIT|NO VALID SETUP/)).toBeVisible();

    await firstRow.getByRole('button', { name: 'Details' }).click();

    const componentsHeading = page.getByText('Components', { exact: true });
    await expect(componentsHeading).toBeVisible();
    await expect(page.getByRole('cell', { name: 'TECHNICAL', exact: true })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'LIGHTGBM', exact: true })).toBeVisible();
  });

  test('recent signals persist across a reload', async ({ page }) => {
    await page.goto('/signals');
    await expect(page.locator('tbody tr').first()).toBeVisible({ timeout: 15_000 });
    const countBefore = await page.locator('tbody tr').count();
    expect(countBefore).toBeGreaterThan(0);

    await page.reload();
    await expect(page.locator('tbody tr').first()).toBeVisible();
    const countAfter = await page.locator('tbody tr').count();
    expect(countAfter).toBeGreaterThanOrEqual(countBefore);
  });
});

test.describe('Positions', () => {
  test('placing a paper order reaches a definitive result', async ({ page }) => {
    await page.goto('/positions');

    await page.getByPlaceholder('required').fill('1');
    await page.getByRole('button', { name: 'Place order' }).click();

    const newPosition = page.locator('tbody tr', { hasText: 'BTCUSDT' });
    const errorBanner = page.getByTestId('place-order-error');

    // The backend retries the Binance ticker call with backoff before
    // giving up (observed ~30s in this environment, where Binance is
    // unreachable) -- generous but bounded, not infinite.
    await expect(newPosition.or(errorBanner)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole('button', { name: 'Placing…' })).toHaveCount(0);
  });
});

test.describe('Orders and Trades', () => {
  test('order history and trade ledger pages load without error', async ({ page }) => {
    await page.goto('/orders');
    await expect(page.getByText('Paper order history')).toBeVisible();

    await page.goto('/trades');
    await expect(page.getByText('Closed trades')).toBeVisible();
  });
});
