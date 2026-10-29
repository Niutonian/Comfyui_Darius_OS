import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
export default defineConfig({
  testDir: '.', testMatch: '*.spec.mjs', fullyParallel: false, workers: 1,
  timeout: 45_000, globalTimeout: 300_000, forbidOnly: !!process.env.CI,
  retries: 0, reporter: 'list', outputDir: '../../test-results/browser',
  use: { baseURL: 'http://127.0.0.1:3100', serviceWorkers: 'block', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'phone', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: 'node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3100',
    cwd: root + 'apps/web', url: 'http://127.0.0.1:3100', reuseExistingServer: false,
    env: { DARIUS_NEXT_DIST_DIR: process.env.DARIUS_E2E_DIST_DIR || '.next-check' },
    timeout: 120_000,
  },
});
