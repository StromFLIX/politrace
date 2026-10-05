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
  use: {
    baseURL: deployedUrl || 'http://127.0.0.1:4321', trace: 'on-first-retry',
    // Citation round-trips visit dozens of large documents in a 1 GB container.
    // Do not retain every old DOM in Chromium's back/forward cache during these checks.
    launchOptions: { args: ['--disable-features=BackForwardCache'] },
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1080 } } },
    { name: 'mobile', use: { ...devices['iPhone 13'], defaultBrowserType: 'chromium' } },
  ],
  webServer: deployedUrl ? undefined : {
    // Test the already-built static output without retaining Astro/Vite's build graph in RAM.
    // Docker CI separately checks the actual production nginx headers and health endpoint.
    command: 'python -m http.server 4321 --bind 127.0.0.1 --directory dist',
    url: 'http://127.0.0.1:4321', reuseExistingServer: !process.env.CI,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
  },
});
