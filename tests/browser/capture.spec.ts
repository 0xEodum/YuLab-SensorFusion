import { test, expect, type Page } from "@playwright/test";

function npy(bytes: ArrayBuffer, kind: "f32" | "u32") {
  const view = new DataView(bytes);
  expect(String.fromCharCode(...new Uint8Array(bytes, 1, 5))).toBe("NUMPY");
  const headerLength = view.getUint16(8, true);
  const offset = 10 + headerLength;
  return kind === "f32"
    ? new Float32Array(bytes, offset)
    : new Uint32Array(bytes, offset);
}

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
  const jobId = (await panes.first().getAttribute("src"))!.split("/")[4];
  const job = await page.evaluate(async (jobId) =>
    fetch(`/api/v1/jobs/${jobId}`).then((response) => response.json()), jobId,
  );
  const raw = await page.evaluate(async ({ jobId, depthId, instanceId }) => {
    const load = async (id: string) => {
      const response = await fetch(`/api/v1/jobs/${jobId}/artifacts/${id}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      const result: number[] = [];
      for (const byte of bytes) result.push(byte);
      return result;
    };
    return { depth: await load(depthId), instance: await load(instanceId) };
  }, {
    jobId,
    depthId: job.result.artifacts.depth.id,
    instanceId: job.result.artifacts.instance.id,
  });
  const depthBytes = new Uint8Array(raw.depth as number[]).buffer;
  const instanceBytes = new Uint8Array(raw.instance as number[]).buffer;
  const depth = npy(depthBytes, "f32") as Float32Array;
  const instance = npy(instanceBytes, "u32") as Uint32Array;
  expect(depth).toHaveLength(640 * 384);
  expect(instance).toHaveLength(640 * 384);
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
  await page.getByRole("button", { name: "Capture RGB and references" }).click();
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
  await page.getByRole("button", { name: "Capture RGB and references" }).click();
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
    "depth", "depth_preview", "instance", "instance_preview", "metadata", "rgb",
  ]);
});
