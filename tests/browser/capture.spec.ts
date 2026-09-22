import { test, expect, type Page } from "@playwright/test";

async function worldReady(page: Page) {
  await expect.poll(
    () => page.evaluate(() => window.worldQA?.metrics().status.ready ?? false),
    { timeout: 45_000 },
  ).toBe(true);
}

test("saved rig capture publishes synchronized fixed-size RGB, depth and ID panes", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/?view=world&site=aerodrome&qa=1");
  await worldReady(page);
  await page.getByRole("button", { name: "Unobstructed F-16" }).click();
  await worldReady(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByRole("button", { name: "Capture RGB and references" }).click();
  await expect(page.getByRole("status", { name: "Capture status" })).toContainText("succeeded", { timeout: 120_000 });
  const panes = page.locator("[data-capture-id]");
  await expect(panes).toHaveCount(3);
  const ids = await panes.evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-capture-id")));
  expect(new Set(ids).size).toBe(1);
  for (const pane of await panes.all()) {
    await expect(pane).toHaveAttribute("data-width", "640");
    await expect(pane).toHaveAttribute("data-height", "384");
  }
  const before = await panes.evaluateAll((nodes) => nodes.map((n) => n.getAttribute("src")));
  await page.setViewportSize({ width: 900, height: 700 });
  await page.mouse.move(500, 400);
  await page.mouse.down();
  await page.mouse.move(600, 430);
  await page.mouse.up();
  expect(await panes.evaluateAll((nodes) => nodes.map((n) => n.getAttribute("src")))).toEqual(before);
});

test("capture cancellation is explicit and never exposes synchronized panes", async ({ page }) => {
  await page.goto("/?view=world&site=aerodrome&qa=1&captureDelay=1500");
  await worldReady(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByRole("button", { name: "Capture RGB and references" }).click();
  await expect(page.getByRole("button", { name: "Cancel capture" })).toBeEnabled();
  await page.getByRole("button", { name: "Cancel capture" }).click();
  await expect(page.getByRole("status", { name: "Capture status" })).toContainText("cancelled", { timeout: 30_000 });
  await expect(page.locator("[data-capture-id]")).toHaveCount(0);
});
