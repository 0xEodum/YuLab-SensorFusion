import { test, expect, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

async function ready(page: Page) {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const r = window.worldQA;
          if (!r) return false;
          const focus =
            r.navigation === "flight" ? r.camera.position : r.controls.target;
          const expected = `${Math.floor(focus.x / 128)},${Math.floor(focus.z / 128)}@${r.pitch}`;
          const m = r.metrics();
          return m.status.ready && m.desired === expected;
        }),
      { timeout: 45000 },
    )
    .toBe(true);
  await expect(page.locator(".world-canvas")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 45000 },
  );
}
test("self-contained catalog, aircraft scale, streamed airfield and real geometry visibility fixtures", async ({
  page,
}) => {
  test.setTimeout(180000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?view=world&site=aerodrome&qa=1");
  await expect(
    page.getByRole("button", { name: "Open aerodrome" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(
      () => page.evaluate(() => window.worldQA?.metrics().assetTemplates ?? 0),
      { timeout: 45000 },
    )
    .toBe(3);
  await ready(page);
  expect(
    (await page.evaluate(() => window.worldQA!.metrics())).assetIds,
  ).toHaveLength(5);
  mkdirSync("artifacts/sf04/browser", { recursive: true });
  await page
    .locator(".world-canvas")
    .screenshot({ path: "artifacts/sf04/browser/aerodrome.png" });
  await page.getByLabel("World camera").selectOption("opening");
  await ready(page);
  expect(
    await page.evaluate(() => window.worldQA!.camera.position.y),
  ).toBeCloseTo(28, 5);
  for (const [name, id] of [
    ["F-16", "f16"],
    ["RQ-4", "rq4"],
    ["vehicle", "ground-vehicle"],
  ]) {
    await page
      .getByRole("button", { name: `Inspect ${name}`, exact: true })
      .click();
    await ready(page);
    await page
      .locator(".world-canvas")
      .screenshot({ path: `artifacts/sf04/browser/${id}.png` });
  }
  const fractions: Record<string, unknown> = {};
  for (const [id, label] of [
    ["clear", "Unobstructed F-16"],
    ["partial", "Partial hangar occlusion"],
    ["hidden", "Closed hangar"],
  ]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await ready(page);
    await page
      .locator(".world-canvas")
      .screenshot({ path: `artifacts/sf04/browser/${id}.png` });
    const counts = await page.evaluate(
      (id) => window.worldQA!.inspectVisibility(id),
      id,
    );
    expect(counts.isolated).toBeGreaterThan(10);
    fractions[id] = counts;
    if (id === "clear") expect(counts.fraction).toBeGreaterThan(0.99);
    if (id === "partial") {
      expect(counts.fraction).toBeGreaterThan(0.05);
      expect(counts.fraction).toBeLessThan(0.95);
    }
    if (id === "hidden") expect(counts.visible).toBe(0);
  }
  const sensors = await page.evaluate(() =>
    window.worldQA!.prepareSensors([210, 28, 15], 100),
  );
  expect(sensors.ids).toContain("aerodrome-0-hidden");
  expect(sensors.structures).toContain("closed-door");
  const before = await page.evaluate(() => window.worldQA!.metrics());
  await page.evaluate(() => window.worldQA!.moveTo(-600, -700));
  await ready(page);
  expect(
    (await page.evaluate(() => window.worldQA!.metrics())).assetIds,
  ).toHaveLength(0);
  await page.getByRole("button", { name: "Inspect RQ-4", exact: true }).click();
  await ready(page);
  expect(
    (await page.evaluate(() => window.worldQA!.metrics())).assetIds.sort(),
  ).toEqual(before.assetIds.sort());
  const baseline = (await page.evaluate(() => window.worldQA!.metrics()))
    .renderer;
  for (let i = 0; i < 3; i++) {
    await page.evaluate(() => window.worldQA!.moveTo(-600, -700));
    await ready(page);
    await page
      .getByRole("button", { name: "Inspect RQ-4", exact: true })
      .click();
    await ready(page);
    const renderer = (await page.evaluate(() => window.worldQA!.metrics()))
      .renderer;
    expect(renderer.geometries).toBe(baseline.geometries);
    expect(renderer.textures).toBe(baseline.textures);
  }
  writeFileSync(
    "artifacts/sf04/browser/acceptance.json",
    JSON.stringify(
      {
        fractions,
        sensors,
        metrics: await page.evaluate(() => window.worldQA!.metrics()),
        errors,
      },
      null,
      2,
    ),
  );
  expect(errors).toEqual([]);
});

test("missing or corrupt asset fails by name and reason, without a substitute", async ({
  page,
}) => {
  await page.route("**/catalog/rq4.glb", (route) =>
    route.fulfill({ status: 404, body: "missing" }),
  );
  await page.goto("/?view=world&site=aerodrome&qa=1");
  await expect(page.getByRole("alert")).toContainText("rq4: HTTP 404", {
    timeout: 45000,
  });
  await expect(page.locator(".world-canvas")).toHaveAttribute(
    "data-ready",
    "false",
  );
  await page.unroute("**/catalog/rq4.glb");
  await page.route("**/catalog/f16.glb", (route) =>
    route.fulfill({ status: 200, body: "corrupt" }),
  );
  await page.reload();
  await expect(page.getByRole("alert")).toContainText(
    "f16: GLB integrity mismatch",
    { timeout: 45000 },
  );
  await page.unroute("**/catalog/f16.glb");
  await page.route("**/catalog/rq4.metadata.json", (route) =>
    route.fulfill({ status: 404, body: "missing" }),
  );
  await page.reload();
  await expect(page.getByRole("alert")).toContainText(
    "rq4: metadata HTTP 404",
    { timeout: 45000 },
  );
  await page.unroute("**/catalog/rq4.metadata.json");
  await page.route("**/catalog/catalog.json", async (route) => {
    const response = await route.fetch();
    const catalog = await response.json();
    catalog.assets = catalog.assets.filter(
      (a: { asset_id: string }) => a.asset_id !== "rq4",
    );
    await route.fulfill({ json: catalog });
  });
  await page.reload();
  await expect(page.locator(".world-canvas [role=alert]")).toContainText(
    "rq4: required catalog record is missing",
  );
  expect(await page.evaluate(() => window.worldQA)).toBeUndefined();
});
