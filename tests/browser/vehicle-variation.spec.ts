import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

test("seeded anti-aircraft turrets are present in the rendered mixed apron", async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?view=world&site=airfield-catalog&qa=1");
  const ready = () => expect.poll(() => page.evaluate(() => {
    const runtime = window.worldQA;
    if (!runtime) return false;
    const focus = runtime.controls.target;
    const metrics = runtime.metrics();
    return metrics.status.ready &&
      metrics.desired === `${Math.floor(focus.x / 128)},${Math.floor(focus.z / 128)}@${runtime.pitch}`;
  }), { timeout: 45_000 }).toBe(true);
  await ready();
  const poses = await page.evaluate(() => {
    const runtime = window.worldQA!;
    const spec = (runtime as any).spec;
    return spec.instances.filter((instance: any) =>
      ["ground-vehicle", "spaa"].includes(instance.asset_id)).map((instance: any) => {
      const asset = runtime.scene.getObjectByName(instance.instance_id);
      const turret = asset?.getObjectByName("turret-yaw");
      return {
        asset_id: instance.asset_id,
        operating_state: instance.operating_state,
        angle: turret?.rotation.y,
        meshes: turret?.children.length,
      };
    });
  });
  expect(poses.map((pose: any) => pose.asset_id)).toEqual(["ground-vehicle", "spaa"]);
  expect(poses.every((pose: any) => Number.isFinite(pose.angle) && pose.meshes > 0)).toBe(true);
  expect(poses[0].angle).not.toBe(poses[1].angle);
  await page.evaluate(() => window.worldQA!.inspectAsset("spaa"));
  await ready();
  await expect(page.locator(".world-canvas")).toHaveAttribute("data-ready", "true");
  mkdirSync("artifacts/vehicle-variation", { recursive: true });
  await page.locator(".world-canvas").screenshot({ path: "artifacts/vehicle-variation/spaa.png" });
  expect(errors).toEqual([]);
});
