import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

/**
 * Phase 39 portal smoke + accessibility (Prompts/39 §39.11 step 11 / §39.12): each persona signs in, lands on its
 * branded portal and the 12 pages below show 0 serious / critical axe violations. Credentials come from the
 * environment (E2E_<PERSONA>_USER / E2E_<PERSONA>_PASS — see LOCAL_TEST_CREDENTIALS.md, never committed); personas
 * without credentials are skipped. Results land in results.json (`axe` attachment per page).
 */
const PAGES: [string, string[]][] = [
  ['STUDENT', ['/student', '/student/requests', '/student/documents', '/student/payments', '/student/notifications', '/student/more']],
  ['PARENT', ['/parent', '/parent/payments']],
  ['FACULTY', ['/faculty', '/faculty/approvals', '/faculty/notifications/settings', '/faculty/timeline']],
];

async function login(page: Page, user: string, pass: string) {
  await page.goto('/login');
  await page.getByLabel(/username|email|phone/i).fill(user);
  await page.getByLabel(/password/i).fill(pass);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'));
}

for (const [persona, routes] of PAGES) {
  test.describe(`${persona.toLowerCase()} portal`, () => {
    const user = process.env[`E2E_${persona}_USER`];
    const pass = process.env[`E2E_${persona}_PASS`];
    test.skip(!user || !pass, `E2E_${persona}_USER / _PASS not set`);
    for (const route of routes) {
      test(`${route} renders and passes axe`, async ({ page }, info) => {
        await login(page, user!, pass!);
        await page.goto(route);
        await expect(page.locator('#portal-main')).toBeVisible();
        const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
        await info.attach('axe', { body: JSON.stringify(result.violations, null, 2), contentType: 'application/json' });
        const bad = result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
        expect(bad.map((v) => v.id)).toEqual([]);
      });
    }
  });
}

test('public manifest is served with the manifest MIME type', async ({ request }) => {
  const r = await request.get('/api/v1/public/manifest.json');
  expect(r.ok()).toBeTruthy();
  expect(r.headers()['content-type']).toContain('application/manifest+json');
  expect((await r.json()).start_url).toBe('/login?source=pwa');
});
