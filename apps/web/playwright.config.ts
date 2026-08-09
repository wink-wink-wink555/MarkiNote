import { defineConfig, devices } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const webRoot = fileURLToPath(new URL('.', import.meta.url));
const localChrome = process.env.CI ? {} : { channel: 'chrome' as const };
const previewManagedByRunner = process.env.MARKINOTE_E2E_MANAGED_PREVIEW === '1';
const baseURL = process.env.MARKINOTE_E2E_BASE_URL ?? 'http://127.0.0.1:4173';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 2,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL, trace: 'on-first-retry', screenshot: 'only-on-failure' },
  webServer: previewManagedByRunner ? undefined : {
    command: 'node ./node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 4173',
    cwd: webRoot,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], ...localChrome } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 7'], ...localChrome } },
  ],
});
