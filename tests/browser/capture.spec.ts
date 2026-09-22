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

test("saved rig capture publishes synchronized RGB, IR, depth and ID panes with calibrated raw IR", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/?view=world&site=aerodrome&qa=1");
  await worldReady(page);
  await page.getByRole("button", { name: "Unobstructed F-16" }).click();
  await worldReady(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByRole("button", { name: "Capture RGB, IR and references" }).click();
  await expect(page.getByRole("status", { name: "Capture status" })).toContainText("succeeded", { timeout: 120_000 });
  const panes = page.locator("[data-capture-id]");
  await expect(panes).toHaveCount(4);
  const ids = await panes.evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-capture-id")));
  expect(new Set(ids).size).toBe(1);
  for (const pane of await panes.all()) {
    await expect(pane).toHaveAttribute("data-width", "640");
    await expect(pane).toHaveAttribute("data-height", "384");
  }
  const jobId = (await panes.first().getAttribute("src"))!.split("/")[4];
  const job = await page.evaluate(async (jobId) =>
    fetch(`/api/v1/jobs/${jobId}`).then((response) => response.json()), jobId,
  );
  const raw = await page.evaluate(async ({ jobId, depthId, instanceId, radianceId, validityId, saturationId, stateId, metadataId }) => {
    const load = async (id: string) => {
      const response = await fetch(`/api/v1/jobs/${jobId}/artifacts/${id}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      const result: number[] = [];
      for (const byte of bytes) result.push(byte);
      return result;
    };
    const text = async (id: string) => {
      const response = await fetch(`/api/v1/jobs/${jobId}/artifacts/${id}`);
      return response.text();
    };
    return {
      depth: await load(depthId),
      instance: await load(instanceId),
      radiance: await load(radianceId),
      validity: await load(validityId),
      saturation: await load(saturationId),
      state: await text(stateId),
      metadata: await text(metadataId),
    };
  }, {
    jobId,
    depthId: job.result.artifacts.depth.id,
    instanceId: job.result.artifacts.instance.id,
    radianceId: job.result.artifacts.ir_radiance.id,
    validityId: job.result.artifacts.ir_validity.id,
    saturationId: job.result.artifacts.ir_saturation.id,
    stateId: job.result.artifacts.thermal_state.id,
    metadataId: job.result.artifacts.metadata.id,
  });
  const depthBytes = new Uint8Array(raw.depth as number[]).buffer;
  const instanceBytes = new Uint8Array(raw.instance as number[]).buffer;
  const depth = npy(depthBytes, "f32") as Float32Array;
  const instance = npy(instanceBytes, "u32") as Uint32Array;
  const radiance = npy(new Uint8Array(raw.radiance as number[]).buffer, "f32") as Float32Array;
  const validity = npy(new Uint8Array(raw.validity as number[]).buffer, "u8") as Uint8Array;
  const saturation = npy(new Uint8Array(raw.saturation as number[]).buffer, "u8") as Uint8Array;
  expect(depth).toHaveLength(640 * 384);
  expect(instance).toHaveLength(640 * 384);
  expect(radiance).toHaveLength(640 * 384);
  expect(validity).toHaveLength(640 * 384);
  expect(saturation).toHaveLength(640 * 384);
  expect([...validity].some((value) => value === 1)).toBe(true);
  expect([...radiance].some((value) => value > 0)).toBe(true);
  for (let i = 0; i < radiance.length; i++) {
    if (!validity[i]) expect(radiance[i]).toBe(0);
    expect(saturation[i]).toBeLessThanOrEqual(1);
  }
  const thermalState = JSON.parse(raw.state as string);
  expect(thermalState.version).toBe("thermal-state.v1");
  const f16 = thermalState.nodes.filter((node: any) => node.instance_id === "aerodrome-0-clear");
  const body = f16.find((node: any) => node.region_id === "body-surface").temperature_k;
  const exhaust = f16.find((node: any) => node.region_id === "exhaust-surface").temperature_k;
  expect(exhaust).toBeGreaterThan(body + 20);
  const metadata = JSON.parse(raw.metadata as string);
  expect(metadata.ir_calibration).toMatchObject({
    response_version: "lwir-8-14um.v1",
    band_um: [8, 14],
    radiance_units: "W/m2/sr",
    palette_applies_to_raw: false,
  });
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
});

test("capture cancellation is explicit and never exposes synchronized panes", async ({ page }) => {
  await page.goto("/?view=world&site=aerodrome&qa=1&captureDelay=1500");
  await worldReady(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  await page.getByRole("button", { name: "Capture RGB, IR and references" }).click();
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
  await page.getByRole("button", { name: "Capture RGB, IR and references" }).click();
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
    "ir_radiance", "ir_saturation", "ir_validity", "metadata", "rgb", "thermal_state",
  ]);
});
