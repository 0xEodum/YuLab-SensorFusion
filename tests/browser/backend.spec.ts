import { test, expect } from '@playwright/test';

test('real backend is reachable through Vite and reports only implemented capabilities', async ({ page, request }) => {
  const health = await request.get('/api/v1/health');
  expect(health.status()).toBe(200);
  expect((await health.json()).status).toBe('ok');
  const capabilities = await (await request.get('/api/v1/capabilities')).json();
  expect(capabilities.sensors.ir.available).toBe(false);
  expect(capabilities.services.training.available).toBe(false);
  await page.goto('/');
  await expect(page.getByLabel('Lab backend')).toContainText('Backend connected');
  await expect(page.getByLabel('Lab backend')).toContainText('not implemented yet');
});

test('connection loss and recovery are explicit without disabling the editor', async ({ page }) => {
  await page.route('**/api/v1/**', route => route.abort());
  await page.goto('/');
  await expect(page.getByLabel('Lab backend')).toContainText('Backend unavailable');
  await expect(page.locator('.terrain-canvas canvas')).toBeVisible();
  await page.getByRole('spinbutton', { name: 'World seed' }).fill('42');
  await expect(page.getByRole('button', { name: 'Export terrain', exact: true })).toBeEnabled();
  await page.screenshot({ path: 'artifacts/browser/backend-offline.png', fullPage: true });
  await page.unroute('**/api/v1/**');
  await page.getByRole('button', { name: 'Retry connection' }).click();
  await expect(page.getByLabel('Lab backend')).toContainText('Backend connected');
});

test('incompatible response is not presented as connected', async ({ page }) => {
  await page.route('**/api/v1/capabilities', route => route.fulfill({ json: { schema_version: 'lab.v999' } }));
  await page.goto('/');
  await expect(page.getByLabel('Lab backend')).toContainText('incompatible');
});
