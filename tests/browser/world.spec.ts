import { test, expect } from '@playwright/test';

test('connected preview shows seams and formations, supports seed zero and world-space regions', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/');
  await page.getByRole('link', { name: 'Explore the connected world' }).click();
  const canvas = page.locator('.world-canvas canvas');
  await expect(canvas).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('4 connected chunks');
  const image = () =>
    canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL());
  await expect
    .poll(async () =>
      Number(
        await page.locator('.world-canvas').getAttribute('data-triangles'),
      ),
    )
    .toBeGreaterThan(10000);
  const first = await image();
  await page.screenshot({
    path: 'artifacts/browser/world-oblique.png',
    fullPage: true,
  });
  await page.getByLabel('Chunk boundaries').check();
  await expect.poll(image).not.toBe(first);
  await page.screenshot({
    path: 'artifacts/browser/world-seams.png',
    fullPage: true,
  });
  await page.getByLabel('Chunk boundaries').uncheck();
  await page.getByLabel('World camera').selectOption('opening');
  await page.screenshot({
    path: 'artifacts/browser/world-opening.png',
    fullPage: true,
  });
  await page.getByLabel('World camera').selectOption('top');
  await page.getByLabel('Chunk boundaries').check();
  await page.screenshot({
    path: 'artifacts/browser/world-top-seams.png',
    fullPage: true,
  });
  await page.getByLabel('Chunk boundaries').uncheck();
  await page.getByLabel('World camera').selectOption('oblique');
  await page
    .getByRole('spinbutton', { name: 'Connected world seed' })
    .fill('48291');
  await page.getByRole('button', { name: 'Generate world' }).click();
  await expect.poll(image).not.toBe(first);
  await page
    .getByRole('spinbutton', { name: 'Connected world seed' })
    .fill('0');
  await page.getByRole('button', { name: 'Generate world' }).click();
  await expect.poll(image).toBe(first);
  for (const [value, name] of [
    ['1', 'ridge'],
    ['2', 'islands'],
    ['3', 'coast'],
  ]) {
    await page.getByLabel('World location').selectOption(value);
    await expect.poll(image).not.toBe(first);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await page.screenshot({
      path: `artifacts/browser/world-${name}.png`,
      fullPage: true,
    });
  }
  await page.getByRole('link', { name: 'Preset editor' }).click();
  await expect(page.locator('.terrain-canvas canvas')).toBeVisible();
  expect(errors).toEqual([]);
});

test('world controls and preview fit a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto('/?view=world');
  await expect(page.locator('.world-canvas canvas')).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(375);
  await page.getByLabel('World location').selectOption('1');
  await expect(page.getByRole('status')).toContainText('4 connected chunks');
  await page.screenshot({
    path: 'artifacts/browser/world-mobile.png',
    fullPage: true,
  });
});
