// Desktop smoke suite: the built web app against the fixture API (no backend needed).
//   npm run build --prefix apps/web   (with DARIUS_NEXT_DIST_DIR=.next-check)
//   npm run test:desktop --prefix tests/browser
// The fixture listens on 127.0.0.1:8000, the app's default API address, so stop a
// running Darius API first. Set PW_CHANNEL=chrome to use an installed Chrome.
import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
export default defineConfig({
  testDir: './desktop', testMatch: '*.spec.mjs', fullyParallel: false, workers: 1,
  timeout: 60_000, globalTimeout: 600_000, forbidOnly: !!process.env.CI, retries: 0, reporter: 'list',
  outputDir: '../../test-results/desktop',
  use: { baseURL: 'http://127.0.0.1:3101', serviceWorkers: 'block', trace: 'retain-on-failure', channel: process.env.PW_CHANNEL || undefined },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'phone', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: [
    { command: 'node apps/web/scripts/fixture-api.mjs --port 8000', cwd: root, url: 'http://127.0.0.1:8000/api/v1/health', reuseExistingServer: false, timeout: 20_000 },
    {
      command: 'node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3101',
      cwd: root + 'apps/web', url: 'http://127.0.0.1:3101', reuseExistingServer: false,
      env: { DARIUS_NEXT_DIST_DIR: process.env.DARIUS_E2E_DIST_DIR || '.next-check' }, timeout: 120_000,
    },
  ],
});
