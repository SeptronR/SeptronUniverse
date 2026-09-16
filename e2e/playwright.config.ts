import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright UI suites per round (ADR 0006; Prompts/00 §2). Phase 43 fills the round projects and per-role storage
 * states in e2e/.auth/ (git-ignored). Run against the local stack: BASE_URL=http://localhost:5173 npx playwright test.
 */
const baseURL = process.env.BASE_URL || 'http://localhost:5173';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }], ['json', { outputFile: 'results.json' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  projects: [
    { name: 'round0', testMatch: /round0\/.*\.spec\.ts/ },
    { name: 'round1', testMatch: /round1\/.*\.spec\.ts/ },
    { name: 'round2', testMatch: /round2\/.*\.spec\.ts/ },
    { name: 'round3', testMatch: /round3\/.*\.spec\.ts/ },
    { name: 'round4', testMatch: /round4\/.*\.spec\.ts/ },
    { name: 'round5', testMatch: /round5\/.*\.spec\.ts/ },
  ],
});
