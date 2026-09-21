import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function canvasImage(page: Page) {
  return page.locator('.terrain-canvas canvas').evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
}

test('legacy presets, seed, navigation and real exports survive the workspace move', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.locator('.terrain-canvas canvas')).toBeVisible();
  await expect(page.getByText('3D rendering is unavailable')).toHaveCount(0);
  for (const [name, seed] of [['Alpine peaks', '81327'], ['Floating islands', '26018'], ['Coastal cliffs', '71042'], ['Canyon arches', '48291']]) {
    await page.locator('.preset-card').filter({ hasText: name }).click();
    await expect(page.getByRole('spinbutton', { name: 'World seed' })).toHaveValue(seed);
    await expect(page.locator('.scene-preset')).toHaveText(name);
  }
  const before = await canvasImage(page);
  await page.getByRole('spinbutton', { name: 'World seed' }).fill('12345');
  await expect.poll(() => canvasImage(page)).not.toBe(before);
  await page.getByRole('button', { name: 'Reset camera', exact: true }).click();
  const cameraBefore = await canvasImage(page);
  const box = await page.locator('.terrain-canvas canvas').boundingBox();
  if (!box) throw new Error('Canvas missing');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 100, box.y + box.height / 2 + 30, { steps: 12 });
  await page.mouse.up();
  await expect.poll(() => canvasImage(page)).not.toBe(cameraBefore);
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await page.getByRole('button', { name: 'Zoom out', exact: true }).click();
  await page.getByRole('button', { name: 'Perspective', exact: true }).click();
  await page.getByRole('button', { name: 'Top-down view', exact: true }).click();
  await page.getByRole('button', { name: 'Reset camera', exact: true }).click();
  for (const [ext, name] of [['png', 'Viewport image'], ['obj', 'Wavefront'], ['glb', '3D model']]) {
    await page.getByRole('button', { name: 'Export terrain', exact: true }).click();
    const downloadPromise = page.waitForEvent('download');
    await page.locator('.export-menu button').filter({ hasText: name }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(`strata-canyon-12345.${ext}`);
    const path = await download.path();
    if (!path) throw new Error('Export did not write a file');
    const bytes = await readFile(path);
    expect(bytes.length).toBeGreaterThan(1000);
    if (ext === 'png') expect(bytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
    if (ext === 'glb') {
      expect(bytes.subarray(0, 4).toString()).toBe('glTF');
      expect(bytes.readUInt32LE(4)).toBe(2);
      expect(bytes.readUInt32LE(8)).toBe(bytes.length);
    }
    if (ext === 'obj') expect(bytes.toString()).toMatch(/^v /m);
  }
  await page.screenshot({ path: 'artifacts/browser/editor-desktop.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('editor remains usable on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto('/');
  await expect(page.locator('.terrain-canvas canvas')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.locator('.guide-button').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.screenshot({ path: 'artifacts/browser/editor-mobile.png', fullPage: true });
});
