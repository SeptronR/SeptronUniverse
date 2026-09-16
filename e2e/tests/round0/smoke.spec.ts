import { expect, test } from '@playwright/test';

/** Round 0 smoke (Phase 00): the Vite shell renders the login placeholder; the API health proxy answers. */
test('login page renders and API health is proxied', async ({ page, request }) => {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'SeptronUniverse' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
  const health = await request.get('/health');
  expect(health.ok()).toBeTruthy();
  expect((await health.json()).status).toBe('ok');
});
