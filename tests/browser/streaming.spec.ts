import { test, expect, type Page } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";
import type { Mesh, InstancedMesh } from "three";
import type { WorldRuntime } from "../../frontend/src/WorldRuntime";

async function ready(page: Page) {
  await page.waitForTimeout(100);
  await expect(page.locator(".world-canvas")).toHaveAttribute(
    "data-ready",
    "true",
    { timeout: 45_000 },
  );
}
const metrics = (page: Page) => page.evaluate(() => window.worldQA!.metrics());

test("worker failure is visible and world edges clip residency without out-of-domain requests", async ({
  page,
}) => {
  await page.route(/chunk\.worker/, (route) => route.abort());
  await page.goto("/?view=world&qa=1");
  await expect(page.getByRole("alert")).toContainText(
    "World preview unavailable",
  );
  await expect(page.locator(".world-canvas")).toHaveAttribute(
    "data-ready",
    "false",
  );
  await page.unroute(/chunk\.worker/);
  await page.reload();
  await ready(page);
  await page.evaluate(() => window.worldQA!.moveTo(-1023, -1023));
  await ready(page);
  let m = await metrics(page);
  expect(m.keys.sort()).toEqual(
    ["-8,-8@4", "-8,-7@4", "-7,-8@4", "-7,-7@4"].sort(),
  );
  await page.evaluate(() => window.worldQA!.moveTo(1023, 1023));
  await ready(page);
  m = await metrics(page);
  expect(m.keys.sort()).toEqual(["6,6@4", "6,7@4", "7,6@4", "7,7@4"]);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("flight, persisted rig bookmarks, cancellation, display LOD and independent sensor readiness", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?view=world&qa=1");
  await ready(page);
  await page.getByLabel("Navigation", { exact: true }).selectOption("flight");
  await ready(page);
  const canvas = page.getByLabel("World navigation canvas");
  await canvas.focus();
  const before = await page.evaluate(() => window.worldQA!.bookmark("before"));
  await page.keyboard.down("KeyW");
  await page.waitForTimeout(400);
  await page.keyboard.up("KeyW");
  const after = await page.evaluate(() => window.worldQA!.bookmark("after"));
  expect(
    Math.hypot(...after.position.map((p, i) => p - before.position[i])),
  ).toBeGreaterThan(5);
  await page.getByLabel("Rig pose name").fill("North approach");
  await ready(page);
  await page.getByRole("button", { name: "Save rig pose" }).click();
  const saved = await page.evaluate(() =>
    window.worldQA!.bookmark("North approach"),
  );
  await page.reload();
  await ready(page);
  await page.getByRole("button", { name: "Restore North approach" }).click();
  await ready(page);
  const restored = await page.evaluate(() =>
    window.worldQA!.bookmark("North approach"),
  );
  for (const field of ["position", "quaternion", "target"] as const)
    for (let i = 0; i < saved[field].length; i++)
      expect(restored[field][i]).toBeCloseTo(saved[field][i], 6);
  await page.getByLabel("Navigation", { exact: true }).selectOption("orbit");
  // Supersede a real worker while meshing a far-away destination.
  await page.evaluate(() => window.worldQA!.moveTo(704, 704));
  await page.waitForTimeout(100);
  await page.evaluate(() => window.worldQA!.moveTo(-64, -64));
  await ready(page);
  let m = await metrics(page);
  expect(m.desired).toBe("-1,-1@4");
  expect(m.worker.cancellations).toBeGreaterThan(0);
  expect(m.keys.every((k) => k.endsWith("@4"))).toBe(true);
  await page.getByLabel("Display detail").selectOption("2");
  await ready(page);
  m = await metrics(page);
  expect(m.keys).toHaveLength(9);
  expect(m.keys.every((k) => k.endsWith("@2"))).toBe(true);
  await page.getByLabel("Chunk boundaries").check();
  await page.screenshot({
    path: "artifacts/sf03/fine-seams.png",
    fullPage: true,
  });
  const displayBefore = m.keys;
  const sensor = await page.evaluate(() =>
    window.worldQA!.prepareSensors([127.9, 80, 64], 40),
  );
  expect(sensor.keys).toContain("1,0@2");
  expect(new Set(sensor.ids).size).toBe(sensor.ids.length);
  expect((await metrics(page)).keys).toEqual(displayBefore);
  expect((await metrics(page)).sensorCache.pinned).toBe(0);
  await page.getByLabel("Display detail").selectOption("4");
  await ready(page);
  // Retain the runtime reference to inspect disposal after the actual React teardown.
  await page.evaluate(() => {
    (window as Window & { retired?: WorldRuntime }).retired = window.worldQA;
  });
  await page
    .getByRole("spinbutton", { name: "Connected world seed" })
    .fill("48291");
  await page.getByRole("button", { name: "Generate world" }).click();
  await ready(page);
  const disposed = await page.evaluate(() => {
    const r = (window as Window & { retired?: WorldRuntime }).retired!;
    return {
      cache: r.cache.snapshot(),
      sensor: r.sensorCache.snapshot(),
      resources: r.chunks.stats,
      canvasConnected: r.renderer.domElement.isConnected,
    };
  });
  expect(disposed.cache.bytes).toBe(0);
  expect(disposed.sensor.bytes).toBe(0);
  expect(disposed.resources.live).toBe(0);
  expect(disposed.resources.created).toBe(disposed.resources.disposed);
  expect(disposed.canvasConnected).toBe(false);
  expect(errors).toEqual([]);
});

test("104 adjacent chunk crossings preserve seams and IDs with bounded production resources", async ({
  page,
  context,
}) => {
  test.setTimeout(360_000);
  mkdirSync("artifacts/sf03", { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1360, height: 1050 });
  await page.goto("/?view=world&qa=1");
  await ready(page);
  // Exact benchmark canvas resolution from the architecture target.
  await page.addStyleTag({
    content:
      ".world-canvas { width: 1280px; height: 720px; } .world-page { max-width: none; }",
  });
  await page.getByLabel("Chunk boundaries").check();
  const cdp = await context.newCDPSession(page);
  const trajectory = Array.from({ length: 105 }, (_, i) => {
    const row = Math.floor(i / 12),
      column = i % 12;
    return { x: -6 + (row % 2 ? 11 - column : column), z: -6 + row };
  });
  const samples: Awaited<ReturnType<typeof metrics>>[] = [];
  const heaps: {
    index: number;
    bytes: number;
    backingStoreBytes: number;
    embedderBytes: number;
  }[] = [];
  const identities = new Map<string, string>();
  let seamPairs = 0;
  for (let i = 0; i < trajectory.length; i++) {
    const c = trajectory[i];
    if (i)
      expect(
        Math.abs(c.x - trajectory[i - 1].x) +
          Math.abs(c.z - trajectory[i - 1].z),
      ).toBe(1);
    await page.evaluate(
      ({ x, z }) => window.worldQA!.moveTo(x * 128 + 64, z * 128 + 64),
      c,
    );
    const expected: string[] = [];
    for (let x = c.x - 1; x <= c.x + 1; x++)
      for (let z = c.z - 1; z <= c.z + 1; z++) expected.push(`${x},${z}@4`);
    await expect.poll(async () => {
      const current = await metrics(page);
      return current.desired === `${c.x},${c.z}@4` && current.status.ready &&
        JSON.stringify([...current.keys].sort()) === JSON.stringify([...expected].sort());
    }, { timeout: 45_000 }).toBe(true);
    const m = await metrics(page);
    expect(m.desired).toBe(`${c.x},${c.z}@4`);
    expect(m.keys.sort()).toEqual(expected.sort());
    expect(m.status.error).toBe("");
    expect(m.cache.chunks).toBeLessThanOrEqual(24);
    expect(m.cache.bytes).toBeLessThanOrEqual(128 * 1024 * 1024);
    expect(m.renderer.geometries).toBeLessThanOrEqual(21);
    expect(m.resources.created - m.resources.disposed).toBe(m.resources.live);
    expect(new Set(m.ids).size).toBe(m.ids.length);
    const inspection = await page.evaluate(() => {
      const r = window.worldQA!,
        meshes = r.chunks.root.children.map((g) => g.children[0] as Mesh);
      const boundaries = (mesh: Mesh, axis: number, coordinate: number) => {
        const p = mesh.geometry.getAttribute("position"),
          n = mesh.geometry.getAttribute("normal"),
          c = mesh.geometry.getAttribute("color");
        const set = new Set<string>();
        for (let i = 0; i < p.count; i++)
          if (p.array[i * 3 + axis] === coordinate)
            set.add(
              [
                p.getX(i),
                p.getY(i),
                p.getZ(i),
                n.getX(i),
                n.getY(i),
                n.getZ(i),
                c.getX(i),
                c.getY(i),
                c.getZ(i),
              ].join(","),
            );
        return [...set].sort().join(";");
      };
      const failures: string[] = [];
      let pairs = 0;
      for (const mesh of meshes) {
        const [x, z] = mesh.name
          .slice("terrain:".length)
          .split(",")
          .map(Number);
        for (const axis of [0, 2]) {
          const neighbor = meshes.find(
            (m) =>
              m.name ===
              `terrain:${x + Number(axis === 0)},${z + Number(axis === 2)}`,
          );
          if (!neighbor) continue;
          const coord = ((axis === 0 ? x : z) + 1) * 128;
          if (
            boundaries(mesh, axis, coord) !== boundaries(neighbor, axis, coord)
          )
            failures.push(mesh.name);
          pairs++;
        }
      }
      const placements = r.chunks.root.children.map((group) => {
        const mesh = group.children[0] as Mesh;
        const ids = new Set<string>();
        for (const object of group.children)
          if ((object as InstancedMesh).isInstancedMesh)
            for (const id of object.userData.placementIds as string[])
              ids.add(id);
        return { chunk: mesh.name, ids: [...ids].sort().join(",") };
      });
      return { failures, pairs, placements };
    });
    expect(inspection.failures).toEqual([]);
    seamPairs += inspection.pairs;
    const renderedIds = inspection.placements.flatMap((p) =>
      p.ids ? p.ids.split(",") : [],
    );
    expect(renderedIds.sort()).toEqual(m.ids.sort());
    for (const p of inspection.placements) {
      if (identities.has(p.chunk)) expect(p.ids).toBe(identities.get(p.chunk));
      identities.set(p.chunk, p.ids);
    }
    samples.push(m);
    if (i === 12) await page.evaluate(() => window.worldQA!.resetMetrics());
    if (i >= 12 && i % 12 === 0) {
      await cdp.send("HeapProfiler.collectGarbage");
      const heap = await cdp.send("Runtime.getHeapUsage");
      heaps.push({
        index: i,
        bytes: heap.usedSize,
        backingStoreBytes: heap.backingStorageSize,
        embedderBytes: heap.embedderHeapUsedSize,
      });
    }
    if (i === 12 || i === 104)
      await page.screenshot({
        path: `artifacts/sf03/traversal-${i}.png`,
        fullPage: true,
      });
  }
  // A return to the start verifies regenerated placement identities after eviction.
  await page.evaluate(() => window.worldQA!.moveTo(-704, -704));
  await ready(page);
  const returned = await metrics(page);
  expect(returned.ids.sort()).toEqual(samples[0].ids.sort());
  expect(returned.cache.evicted).toBeGreaterThan(100);
  expect(returned.resources.disposed).toBeGreaterThan(100);
  expect(heaps.length).toBeGreaterThanOrEqual(7);
  // Preserve diagnostics even when a memory gate fails, instead of losing the samples.
  writeFileSync(
    "artifacts/sf03/traversal-heaps.json",
    JSON.stringify({ heaps, returned }, null, 2),
  );
  expect(heaps.at(-1)!.bytes).toBeLessThan(
    heaps[0].bytes * 1.5 + 16 * 1024 * 1024,
  );
  expect(heaps.some((h, i) => i > 0 && h.bytes <= heaps[i - 1].bytes)).toBe(
    true,
  );
  expect(errors).toEqual([]);
  const report = {
    profile: "SF-03-production-streaming-v1",
    crossings: 104,
    seamPairs,
    trajectory,
    samples,
    heaps,
    returned,
    userAgent: await page.evaluate(() => navigator.userAgent),
    errors,
  };
  writeFileSync(
    "artifacts/sf03/traversal.json",
    JSON.stringify(report, null, 2),
  );
  if (process.env.PLAYWRIGHT_GPU === "1") {
    expect(returned.frame.p50).toBeLessThanOrEqual(1000 / 30);
    expect(returned.frame.p95).toBeLessThanOrEqual(50);
  }
});
