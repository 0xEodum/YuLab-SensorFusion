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
  await expect(page.getByRole('status')).toContainText('9 connected chunks');
  await expect(page.getByLabel('World location').locator('option')).toHaveCount(
    16,
  );
  await expect(page.locator('.world-canvas')).toHaveAttribute(
    'data-features',
    '16',
  );
  await expect
    .poll(async () =>
      Number(await page.locator('.world-canvas').getAttribute('data-trees')),
    )
    .toBeGreaterThan(0);
  await expect
    .poll(async () =>
      Number(await page.locator('.world-canvas').getAttribute('data-rocks')),
    )
    .toBeGreaterThan(0);
  const image = () =>
    canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL());
  await expect
    .poll(async () =>
      Number(
        await page.locator('.world-canvas').getAttribute('data-triangles'),
      ),
    )
    .toBeGreaterThan(30000);
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
    ['5', 'region-five'],
    ['10', 'region-ten'],
    ['15', 'region-fifteen'],
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

test('captures original and connected formations at comparable browser framing', async ({
  page,
}) => {
  await page.goto('/');
  await expect(page.locator('.terrain-canvas canvas')).toBeVisible();
  for (const [preset, slug] of [
    ['Canyon arches', 'canyon'],
    ['Alpine peaks', 'alpine'],
    ['Floating islands', 'islands'],
    ['Coastal cliffs', 'coast'],
  ]) {
    await page.locator('.preset-card').filter({ hasText: preset }).click();
    await expect(page.locator('.scene-preset')).toHaveText(preset);
    await page.locator('.terrain-canvas').screenshot({
      path: `artifacts/browser/sf02r-legacy-${slug}.png`,
    });
  }

  await page.goto('/?view=world');
  const location = page.getByLabel('World location');
  const camera = page.getByLabel('World camera');
  await expect(location.locator('option')).toHaveCount(16);
  for (const [prefix, slug] of [
    ['Canyon arch', 'canyon'],
    ['Alpine ridge', 'alpine'],
    ['Highland outcrops', 'islands'],
    ['Coastal bluff', 'coast'],
  ]) {
    const labels = await location.locator('option').allTextContents();
    const index = labels.findIndex((label) => label.startsWith(prefix));
    expect(index).toBeGreaterThanOrEqual(0);
    await location.selectOption(String(index));
    await expect
      .poll(async () =>
        Number(
          await page.locator('.world-canvas').getAttribute('data-triangles'),
        ),
      )
      .toBeGreaterThan(30000);
    await page.locator('.world-canvas').screenshot({
      path: `artifacts/browser/sf02r-connected-${slug}-overview-seed-0.png`,
    });
    await camera.selectOption('detail');
    await page.locator('.world-canvas').screenshot({
      path: `artifacts/browser/sf02r-connected-${slug}-detail-seed-0.png`,
    });
    await camera.selectOption('oblique');
  }
  for (const nextSeed of ['48291', '77123']) {
    await page
      .getByRole('spinbutton', { name: 'Connected world seed' })
      .fill(nextSeed);
    await page.getByRole('button', { name: 'Generate world' }).click();
    const labels = await location.locator('option').allTextContents();
    const canyonIndex = labels.findIndex((label) =>
      label.startsWith('Canyon arch'),
    );
    await location.selectOption(String(canyonIndex));
    await page.locator('.world-canvas').screenshot({
      path: `artifacts/browser/sf02r-connected-canyon-overview-seed-${nextSeed}.png`,
    });
    await camera.selectOption('detail');
    await page.locator('.world-canvas').screenshot({
      path: `artifacts/browser/sf02r-connected-canyon-detail-seed-${nextSeed}.png`,
    });
    await camera.selectOption('oblique');
  }
});

test('world controls and preview fit a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto('/?view=world');
  await expect(page.locator('.world-canvas canvas')).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(375);
  await page.getByLabel('World location').selectOption('5');
  await expect(page.getByRole('status')).toContainText('9 connected chunks');
  await page.screenshot({
    path: 'artifacts/browser/world-mobile.png',
    fullPage: true,
  });
});
