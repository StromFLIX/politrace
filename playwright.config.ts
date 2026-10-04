import { defineConfig, devices } from '@playwright/test';
const deployedUrl = process.env.POLITRACE_TEST_BASE_URL;
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Keep browser processes within small CI/container memory budgets.
  workers: 1,
  reporter: [['list']],
  // Full-programme DOM snapshots are large; capture diagnostics only on a failed retry.
  use: { baseURL: deployedUrl || 'http://127.0.0.1:4321', trace: 'on-first-retry' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1080 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: deployedUrl ? undefined : {
    // Playwright owns this process; do not use Astro's background-server/lock lifecycle.
    command: 'npm run preview -- --host 127.0.0.1 --port 4321 --ignore-lock',
    url: 'http://127.0.0.1:4321', reuseExistingServer: !process.env.CI,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
  },
});
