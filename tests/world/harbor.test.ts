import test from "node:test";
import assert from "node:assert/strict";
import { createWorld, harborWorldSpec, harborStructures, HARBOR_WATER_Y } from "@yulab/world";
import type { AssetRecord } from "@yulab/contracts";
import { readFileSync } from "node:fs";
import * as THREE from "three";

const catalog = JSON.parse(readFileSync(new URL("../../frontend/public/catalog/catalog.json", import.meta.url), "utf8"));
const records = catalog.assets as AssetRecord[];

test("harbor is a seeded coast with a dry quay and ships afloat", () => {
  const spec = harborWorldSpec(48291, records);
  const world = createWorld(spec);
  assert.equal(spec.instances.length, 2);
  assert.ok(world.baseHeight(-170, 0) < HARBOR_WATER_Y - 2);
  assert.ok(Math.abs(world.baseHeight(170, 0) - 14) < 0.1);
  for (const instance of spec.instances) {
    const asset = records.find((r) => r.asset_id === instance.asset_id)!;
    const meta = JSON.parse(readFileSync(new URL(`../../frontend/public/catalog/${asset.asset_id}.metadata.json`, import.meta.url), "utf8"));
    assert.equal(asset.class_name, "ship");
    assert.equal(meta.waterline_m, 0);
    assert.equal(instance.T_world_from_asset[7], HARBOR_WATER_Y);
    assert.ok(instance.T_world_from_asset[3] < 0);
    const transform = new THREE.Matrix4().set(...instance.T_world_from_asset);
    const box = new THREE.Box3().setFromCenterAndSize(
      new THREE.Vector3(...asset.bounds.center_m),
      new THREE.Vector3(...asset.bounds.extent_m),
    ).applyMatrix4(transform);
    assert.ok(box.max.x < 64, `${asset.asset_id}: hull touches shoreline`);
    assert.ok(box.min.y < HARBOR_WATER_Y - 4, `${asset.asset_id}: keel immersed`);
    assert.ok(box.max.y > HARBOR_WATER_Y + 25, `${asset.asset_id}: superstructure visible`);
    for (const x of [box.min.x, (box.min.x + box.max.x) / 2, box.max.x])
      assert.ok(world.baseHeight(x, instance.T_world_from_asset[11]) < box.min.y - 2,
        `${asset.asset_id}: keel clearance`);
  }
  assert.ok(harborStructures().some((s) => s.id.startsWith("quay")));
  assert.deepEqual(harborWorldSpec(48291, records), spec);
  assert.notDeepEqual(harborWorldSpec(0, records).instances, spec.instances);
  assert.equal(harborWorldSpec(48291, [], "background").instances.length, 0);
});
