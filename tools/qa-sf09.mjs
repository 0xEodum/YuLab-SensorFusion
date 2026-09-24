import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL ?? "msedge" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const errors = [];
const acceptance = { views: [], visibility: [], errors };
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`);
});
await mkdir("artifacts/sf09/browser", { recursive: true });
const ready = async () => page.waitForFunction(() => {
  const r = window.worldQA;
  if (!r) return false;
  const focus = r.navigation === "flight" ? r.camera.position : r.controls.target;
  const expected = `${Math.floor(focus.x / 128)},${Math.floor(focus.z / 128)}@${r.pitch}`;
  const m = r.metrics();
  return m.status.ready && m.desired === expected;
}, null, { timeout: 60000 });
const shot = async (name) => {
  await ready();
  await page.locator(".world-canvas").screenshot({ path: `artifacts/sf09/browser/${name}.png` });
  const metrics = await page.evaluate(() => window.worldQA.metrics());
  acceptance.views.push({ name, templates: metrics.assetTemplates,
    instances: metrics.assetIds.length, triangles: metrics.status.triangles,
    renderer: metrics.renderer });
  console.log(JSON.stringify({ name, templates: metrics.assetTemplates,
    instances: metrics.assetIds.length, triangles: metrics.status.triangles,
    renderer: metrics.renderer }));
};
try {
  await page.goto("http://127.0.0.1:5173/?view=world&site=harbor&qa=1");
  await shot("harbor-oblique");
  const sensorScene = await page.evaluate(() =>
    window.worldQA.prepareSensors([-150, 20, 0], 135));
  assert.ok(sensorScene.ids.some((id) => id.includes("cruiser-1")));
  assert.ok(sensorScene.ids.some((id) => id.includes("destroyer-2")));
  assert.ok(sensorScene.structures.includes("harbor-water"));
  assert.ok(sensorScene.structures.some((id) => id.startsWith("pier-")));
  acceptance.sensor_scene = sensorScene;
  await page.getByRole("button", { name: "New viewpoint" }).click();
  await ready();
  const firstView = await page.evaluate(() => window.worldQA.camera.position.toArray());
  await page.getByRole("button", { name: "New viewpoint" }).click();
  await ready();
  const secondView = await page.evaluate(() => window.worldQA.camera.position.toArray());
  assert.notDeepEqual(firstView, secondView);
  acceptance.random_views = [firstView, secondView];
  await page.getByLabel("World camera").selectOption("detail");
  await shot("harbor-detail");
  await page.getByLabel("World camera").selectOption("opening");
  await shot("harbor-ground");
  await page.getByRole("button", { name: "Inspect Guided missile cruiser" }).click();
  await shot("cruiser");
  const cruiser = await page.evaluate(() => window.worldQA.inspectVisibility("cruiser-1"));
  assert.ok(cruiser.isolated > 50 && cruiser.fraction > 0.75);
  acceptance.visibility.push({ asset: "cruiser", ...cruiser });
  console.log(JSON.stringify({ name: "cruiser-visibility", value: cruiser }));
  await page.getByRole("button", { name: "Inspect Missile destroyer" }).click();
  await shot("destroyer");
  const destroyer = await page.evaluate(() => window.worldQA.inspectVisibility("destroyer-2"));
  assert.ok(destroyer.isolated > 50 && destroyer.fraction > 0.75);
  acceptance.visibility.push({ asset: "destroyer", ...destroyer });
  console.log(JSON.stringify({ name: "destroyer-visibility", value: destroyer }));
  await page.goto("http://127.0.0.1:5173/?view=world&site=airfield-catalog&qa=1");
  await shot("airfield-mix");
  const instances = await page.evaluate(() => window.worldQA.spec.instances.map((i) =>
    ({ id: i.instance_id, asset: i.asset_id })));
  assert.equal(instances.length, 6);
  for (const instance of instances) {
    await page.evaluate((asset) => window.worldQA.inspectAsset(asset), instance.asset);
    await ready();
    const value = await page.evaluate((id) => window.worldQA.inspectVisibility(id),
      instance.id.replace(/^aerodrome-catalog-0-/, ""));
    assert.ok(value.isolated >= 5 && value.fraction > 0.75, instance.asset);
    acceptance.visibility.push({ asset: instance.asset, ...value });
    console.log(JSON.stringify({ name: "airfield-visibility", ...instance, value }));
  }
  await page.goto("http://127.0.0.1:5173/?view=world&site=harbor-background&qa=1");
  await shot("harbor-empty");
  assert.deepEqual(acceptance.views.map((v) => v.instances), [2, 2, 2, 2, 2, 6, 0]);
  assert.deepEqual(errors, []);
  const screenshots = {};
  for (const view of acceptance.views) {
    const bytes = await readFile(`artifacts/sf09/browser/${view.name}.png`);
    screenshots[view.name] = createHash("sha256").update(bytes).digest("hex");
  }
  acceptance.screenshots_sha256 = screenshots;
  await writeFile("artifacts/sf09/browser/acceptance.json", JSON.stringify(acceptance, null, 2));
  console.log(JSON.stringify({ errors }));
} catch (error) {
  console.error(JSON.stringify({ errors, alert: await page.locator('[role="alert"]').allTextContents(),
    status: await page.evaluate(() => window.worldQA?.metrics().status ?? null) }));
  throw error;
} finally {
  await browser.close();
}
