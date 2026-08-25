import { defineConfig, devices } from '@playwright/test';

// Phase 17 (§16, §17): drives the real UI against a real backend + database.
// Requires the stack already running (docker compose, or the ad-hoc dev
// servers this session used) and e2e/seed.py already run -- this test suite
// intentionally does not start services or seed data itself, the same
// separation a CI pipeline would use (bring up the stack, seed, then test).
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  // The Positions test can wait out a real Binance retry-with-backoff
  // sequence (observed ~30s when Binance is unreachable, as in this
  // session's environment) -- generous but bounded.
  timeout: 90_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH ?? undefined,
        },
      },
    },
  ],
});
