import { test, expect, type Page } from "@playwright/test";

function npy(bytes: ArrayBuffer, kind: "f32" | "u32" | "u8") {
  const view = new DataView(bytes);
  expect(String.fromCharCode(...new Uint8Array(bytes, 1, 5))).toBe("NUMPY");
  const headerLength = view.getUint16(8, true);
  const offset = 10 + headerLength;
  return kind === "f32"
    ? new Float32Array(bytes, offset)
    : kind === "u32"
      ? new Uint32Array(bytes, offset)
      : new Uint8Array(bytes, offset);
}

async function worldReady(page: Page) {
  await expect.poll(
    () => page.evaluate(() => window.worldQA?.metrics().status.ready ?? false),
    { timeout: 45_000 },
  ).toBe(true);
}

test("saved rig capture publishes synchronized RGB, IR, LiDAR, depth and ID panes", async ({ page, request }) => {
  test.setTimeout(240_000);
  await page.goto("/?view=world&site=aerodrome&qa=1");
  await worldReady(page);
  await page.getByRole("button", { name: "Unobstructed F-16" }).click();
  await worldReady(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByRole("button", { name: "Capture RGB, IR, LiDAR and references" }).click();
  await expect(page.getByRole("status", { name: "Capture status" })).toContainText("succeeded", { timeout: 120_000 });
  const panes = page.locator("[data-capture-id]");
  await expect(panes).toHaveCount(6);
  const ids = await panes.evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-capture-id")));
  expect(new Set(ids).size).toBe(1);
  for (const pane of await panes.all()) {
    const range = (await pane.getAttribute("alt"))?.startsWith("LiDAR range");
    await expect(pane).toHaveAttribute("data-width", range ? "512" : "640");
    await expect(pane).toHaveAttribute("data-height", range ? "64" : "384");
  }
  const jobId = (await panes.first().getAttribute("src"))!.split("/")[4];
  const jobResponse = await request.get(`/api/v1/jobs/${jobId}`);
  expect(jobResponse.ok()).toBe(true);
  const job = await jobResponse.json();
  const readArtifact = async (key: string) => {
    const response = await request.get(`/api/v1/jobs/${jobId}/artifacts/${job.result.artifacts[key].id}`);
    expect(response.ok()).toBe(true);
    return response.body();
  };
  const readNpy = async (key: string, kind: "f32" | "u32" | "u8") => {
    const bytes = await readArtifact(key);
    const copy = new ArrayBuffer(bytes.length);
    new Uint8Array(copy).set(bytes);
    return npy(copy, kind);
  };
  const depth = await readNpy("depth", "f32") as Float32Array;
  const instance = await readNpy("instance", "u32") as Uint32Array;
  const radiance = await readNpy("ir_radiance", "f32") as Float32Array;
  const validity = await readNpy("ir_validity", "u8") as Uint8Array;
  const saturation = await readNpy("ir_saturation", "u8") as Uint8Array;
  expect(depth).toHaveLength(640 * 384);
  expect(instance).toHaveLength(640 * 384);
  expect(radiance).toHaveLength(640 * 384);
  expect(validity).toHaveLength(640 * 384);
  expect(saturation).toHaveLength(640 * 384);
  let hasValid = false;
  let hasRadiance = false;
  let invalidPixelsAreZero = true;
  let saturationMaskIsBinary = true;
  for (let i = 0; i < radiance.length; i++) {
    hasValid ||= validity[i] === 1;
    hasRadiance ||= radiance[i] > 0;
    invalidPixelsAreZero &&= validity[i] !== 0 || radiance[i] === 0;
    saturationMaskIsBinary &&= saturation[i] === 0 || saturation[i] === 1;
  }
  expect(hasValid).toBe(true);
  expect(hasRadiance).toBe(true);
  expect(invalidPixelsAreZero).toBe(true);
  expect(saturationMaskIsBinary).toBe(true);
  const thermalState = JSON.parse((await readArtifact("thermal_state")).toString("utf8"));
  expect(thermalState.version).toBe("thermal-state.v1");
  const f16 = thermalState.nodes.filter((node: any) => node.instance_id === "aerodrome-0-clear");
  const body = f16.find((node: any) => node.region_id === "body-surface").temperature_k;
  const exhaust = f16.find((node: any) => node.region_id === "exhaust-surface").temperature_k;
  expect(exhaust).toBeGreaterThan(body + 20);
  const metadata = JSON.parse((await readArtifact("metadata")).toString("utf8"));
  expect(metadata.ir_calibration).toMatchObject({
    response_version: "lwir-8-14um.v1",
    band_um: [8, 14],
    radiance_units: "W/m2/sr",
    palette_applies_to_raw: false,
  });
  expect(metadata.lidar_calibration).toMatchObject({
    version: "lidar-first-return.v1", frame: "lidar-forward-left-up",
    rows: 64, columns: 512,
  });
  const xyz = await readNpy("lidar_xyz", "f32") as Float32Array;
  const beams = await readNpy("lidar_beam_id", "u32") as Uint32Array;
  const statuses = await readNpy("lidar_beam_status", "u8") as Uint8Array;
  const idealInstance = await readNpy("lidar_ideal_instance", "u32") as Uint32Array;
  expect(xyz.length).toBe(metadata.lidar_point_count * 3);
  expect(beams.length).toBe(metadata.lidar_point_count);
  expect(statuses.length).toBe(64 * 512);
  expect(metadata.lidar_point_count).toBeGreaterThan(0);
  expect([...statuses].filter((status) => status === 1).length).toBe(metadata.lidar_point_count);
  expect([...beams].every((id) => id < statuses.length && statuses[id] === 1)).toBe(true);
  expect([...xyz].every(Number.isFinite)).toBe(true);
  expect([...idealInstance].filter((id) => id === job.result.instance_ids["aerodrome-0-clear"]).length).toBeGreaterThan(0);
  expect([...idealInstance].some((id) => id === job.result.instance_ids["aerodrome-0-hidden"])).toBe(false);
  await page.screenshot({ path: "artifacts/sf07/browser/capture-desktop.png", fullPage: true });
  expect(depth[320]).toBe(0);
  expect(depth[(383 * 640) + 320]).toBeGreaterThan(0);
  const visibleId = job.result.instance_ids["aerodrome-0-clear"];
  expect([...instance].some((value) => value === visibleId)).toBe(true);
  expect([...instance].every((value) => value === 0 || Object.values(job.result.instance_ids).includes(value))).toBe(true);
  for (let i = 0; i < instance.length; i++)
    if (instance[i] !== 0) expect(depth[i]).toBeGreaterThan(0);
  const before = await panes.evaluateAll((nodes) => nodes.map((n) => n.getAttribute("src")));
  await page.setViewportSize({ width: 900, height: 700 });
  await page.mouse.move(500, 400);
  await page.mouse.down();
  await page.mouse.move(600, 430);
  await page.mouse.up();
  expect(await panes.evaluateAll((nodes) => nodes.map((n) => n.getAttribute("src")))).toEqual(before);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.screenshot({ path: "artifacts/sf07/browser/capture-mobile.png", fullPage: true });
});

test("capture cancellation is explicit and never exposes synchronized panes", async ({ page }) => {
  await page.goto("/?view=world&site=aerodrome&qa=1&captureDelay=1500");
  await worldReady(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByRole("button", { name: "Capture RGB, IR, LiDAR and references" }).click();
  await expect(page.getByRole("button", { name: "Cancel capture" })).toBeEnabled();
  await page.getByRole("button", { name: "Cancel capture" }).click();
  await expect(page.getByRole("status", { name: "Capture status" })).toContainText("cancelled", { timeout: 30_000 });
  await expect(page.locator("[data-capture-id]")).toHaveCount(0);
});

test("closing the submitting browser does not stop an accepted backend job", async ({ page, request }) => {
  test.setTimeout(180_000);
  await page.goto("/?view=world&site=aerodrome&qa=1");
  await worldReady(page);
  await page.getByRole("button", { name: "Unobstructed F-16" }).click();
  await worldReady(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  const accepted = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/captures") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Capture RGB, IR, LiDAR and references" }).click();
  const job = await (await accepted).json();
  expect(job.state).toBe("queued");
  await page.close();
  await expect.poll(async () => {
    const response = await request.get(`/api/v1/jobs/${job.job_id}`);
    return (await response.json()).state;
  }, { timeout: 120_000 }).toBe("succeeded");
  const status = await request.get(`/api/v1/jobs/${job.job_id}`);
  const completed = await status.json();
  expect(Object.keys(completed.result.artifacts).sort()).toEqual([
    "depth", "depth_preview", "instance", "instance_preview", "ir_preview",
    "ir_radiance", "ir_saturation", "ir_validity", "lidar_beam_id",
    "lidar_beam_status", "lidar_cloud_preview", "lidar_ideal_instance", "lidar_ideal_range",
    "lidar_intensity", "lidar_range_preview", "lidar_time_offset", "lidar_validity",
    "lidar_xyz", "metadata", "rgb", "thermal_state",
  ]);
});
