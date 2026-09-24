import { test, expect } from "@playwright/test";

test("harbor capture carries ship identity through RGB, IR and first-return references", async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.goto("/?view=world&site=harbor&qa=1");
  await expect.poll(() => page.evaluate(() => window.worldQA?.metrics().status.ready ?? false),
    { timeout: 45_000 }).toBe(true);
  await page.getByRole("button", { name: "Inspect Guided missile cruiser" }).click();
  await expect.poll(() => page.evaluate(() => window.worldQA?.metrics().status.ready ?? false),
    { timeout: 45_000 }).toBe(true);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByRole("button", { name: "Capture RGB, IR, LiDAR and references" }).click();
  await expect(page.getByRole("status", { name: "Capture status" }))
    .toContainText("succeeded", { timeout: 120_000 });
  const panes = page.locator("[data-capture-id]");
  await expect(panes).toHaveCount(7);
  const jobId = (await panes.first().getAttribute("src"))!.split("/")[4];
  const jobResponse = await request.get(`/api/v1/jobs/${jobId}`);
  expect(jobResponse.ok()).toBe(true);
  const job = await jobResponse.json();
  const cruiser = job.result.instance_ids["harbor-mixed-0-cruiser-1"];
  const destroyer = job.result.instance_ids["harbor-mixed-0-destroyer-2"];
  expect(cruiser).toBeGreaterThan(0);
  expect(destroyer).toBeGreaterThan(0);
  const artifact = async (key: string) => {
    const response = await request.get(`/api/v1/jobs/${jobId}/artifacts/${job.result.artifacts[key].id}`);
    expect(response.ok()).toBe(true);
    return response.body();
  };
  const instances = await artifact("instance");
  const headerLength = instances.readUInt16LE(8);
  const copy = new ArrayBuffer(instances.length);
  new Uint8Array(copy).set(instances);
  const ids = new Uint32Array(copy, 10 + headerLength,
    (instances.length - 10 - headerLength) / 4);
  expect([...ids].some((id) => id === cruiser)).toBe(true);
  const thermal = JSON.parse((await artifact("thermal_state")).toString("utf8"));
  for (const id of ["harbor-mixed-0-cruiser-1", "harbor-mixed-0-destroyer-2"])
    expect(thermal.nodes.some((node: { instance_id: string }) => node.instance_id === id)).toBe(true);
  const metadata = JSON.parse((await artifact("metadata")).toString("utf8"));
  expect(metadata.lidar_calibration.class_table.some((item: { name: string }) => item.name === "ship"))
    .toBe(true);
  await page.locator(".world-canvas").screenshot({ path: "artifacts/sf09/browser/harbor-capture-view.png" });
});
