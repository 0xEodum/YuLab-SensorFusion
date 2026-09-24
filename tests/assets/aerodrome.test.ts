import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import * as THREE from "three";
import {
  aerodromeWorldSpec,
  aerodromeStructures,
  createWorld,
  chunkPlacements,
  meshChunk,
} from "@yulab/world";
import { validateCatalog } from "@yulab/assets";

const catalog = validateCatalog(
  JSON.parse(
    readFileSync(
      new URL("../../frontend/public/catalog/catalog.json", import.meta.url),
      "utf8",
    ),
  ),
);
test("invalid catalog identities and non-rigid instance transforms fail explicitly", () => {
  assert.throws(
    () => validateCatalog({ ...catalog, assets: catalog.assets.slice(1) }),
    /f16.*missing/,
  );
  assert.throws(
    () =>
      validateCatalog({
        ...catalog,
        assets: [...catalog.assets, catalog.assets[0]],
      }),
    /duplicate/,
  );
  const spec = aerodromeWorldSpec(0, catalog.assets);
  spec.instances[0].T_world_from_asset[0] = 0.5;
  assert.throws(() => createWorld(spec), /rigid yaw-only/);
});
test("graded site is deterministic, metre-scaled and free of ground / building / placement intersections", () => {
  for (const seed of [0, 48291, 7]) {
    const spec = aerodromeWorldSpec(seed, catalog.assets),
      world = createWorld(spec);
    assert.deepEqual(spec, aerodromeWorldSpec(seed, catalog.assets));
    assert.equal(spec.instances.length, 5);
    const bounds: THREE.Box3[] = [];
    for (const i of spec.instances) {
      const record = catalog.assets.find((a) => a.asset_id === i.asset_id)!;
      const transform = new THREE.Matrix4().set(...i.T_world_from_asset);
      const box = new THREE.Box3()
        .setFromCenterAndSize(
          new THREE.Vector3(...record.bounds.center_m),
          new THREE.Vector3(...record.bounds.extent_m),
        )
        .applyMatrix4(transform);
      assert.ok(Math.abs(box.min.y - 24.04) < 0.0001);
      for (const b of bounds)
        assert.equal(box.intersectsBox(b), false, i.instance_id);
      bounds.push(box);
      for (const s of aerodromeStructures().filter(
        (s) => s.kind === "building",
      )) {
        const b = new THREE.Box3().setFromCenterAndSize(
          new THREE.Vector3(...s.center),
          new THREE.Vector3(...s.size),
        );
        assert.equal(
          box.intersectsBox(b),
          false,
          `${i.instance_id} intersects ${s.id}`,
        );
      }
      const meta = JSON.parse(
        readFileSync(
          new URL(
            `../../frontend/public/catalog/${i.asset_id}.metadata.json`,
            import.meta.url,
          ),
          "utf8",
        ),
      );
      for (const contact of meta.contacts_m) {
        const v = new THREE.Vector3(
          ...(contact as [number, number, number]),
        ).applyMatrix4(transform);
        assert.ok(Math.abs(v.y - 24.04) < 0.015);
        assert.equal(world.baseHeight(v.x, v.z), 24);
        assert.ok(Math.abs(world.density(v.x, 24, v.z)) < 1e-9);
      }
    }
    // The runway remains flat across 11 chunk boundaries and blends continuously at shoulders.
    for (let z = -600; z <= 600; z += 8)
      assert.equal(world.baseHeight(-80, z), 24);
    for (const x of [-192, -160, 288, 320]) {
      const h = world.baseHeight(x, 0);
      assert.ok(Math.abs(world.baseHeight(x + 1e-5, 0) - h) < 1e-4);
    }
    for (const c of [
      { x: 0, z: 0 },
      { x: 1, z: 0 },
      { x: -1, z: 0 },
    ])
      assert.equal(chunkPlacements(world, c).length, 0);
  }
  assert.notDeepEqual(
    aerodromeWorldSpec(0, catalog.assets).instances,
    aerodromeWorldSpec(7, catalog.assets).instances,
  );
  assert.throws(() => aerodromeWorldSpec(0, []), /f16.*missing/);
});

test("graded chunk geometry agrees at boundaries in both display pitches and reverse request order", () => {
  const world = createWorld(aerodromeWorldSpec(0, catalog.assets));
  const hash = (mesh: ReturnType<typeof meshChunk>) =>
    createHash("sha256")
      .update(new Uint8Array(mesh.positions.buffer))
      .digest("hex");
  for (const pitch of [2, 4]) {
    const a = meshChunk(world, { x: -2, z: 0 }, pitch),
      b = meshChunk(world, { x: -1, z: 0 }, pitch);
    assert.equal(hash(b), hash(meshChunk(world, { x: -1, z: 0 }, pitch)));
    assert.equal(hash(a), hash(meshChunk(world, { x: -2, z: 0 }, pitch)));
    const edge = (m: typeof a) => {
      const values = new Set<string>();
      for (let i = 0; i < m.positions.length; i += 3)
        if (m.positions[i] === -128)
          values.add(
            `${m.positions[i + 1].toFixed(5)},${m.positions[i + 2].toFixed(5)}`,
          );
      return [...values].sort();
    };
    assert.ok(edge(a).length > 0);
    assert.deepEqual(edge(a), edge(b));
  }
});

test("seeded mixed apron uses grounded aircraft and vehicles without overlaps", () => {
  const rosters = new Set<string>();
  for (const seed of [0, 1, 7, 48291, 9001]) {
    const spec = aerodromeWorldSpec(seed, catalog.assets, "catalog");
    assert.deepEqual(spec, aerodromeWorldSpec(seed, catalog.assets, "catalog"));
    assert.equal(spec.instances.length, 6);
    assert.equal(spec.instances.filter((i) =>
      catalog.assets.find((a) => a.asset_id === i.asset_id)!.class_name === "aircraft").length, 4);
    rosters.add(spec.instances.map((i) => i.asset_id).join(","));
    const boxes: THREE.Box3[] = [];
    for (const instance of spec.instances) {
      const record = catalog.assets.find((a) => a.asset_id === instance.asset_id)!;
      const transform = new THREE.Matrix4().set(...instance.T_world_from_asset);
      const box = new THREE.Box3().setFromCenterAndSize(
        new THREE.Vector3(...record.bounds.center_m),
        new THREE.Vector3(...record.bounds.extent_m),
      ).applyMatrix4(transform);
      assert.ok(Math.abs(box.min.y - 24.04) < 0.08, instance.asset_id);
      for (const prior of boxes) assert.equal(box.intersectsBox(prior), false, instance.asset_id);
      boxes.push(box);
      const meta = JSON.parse(readFileSync(new URL(
        `../../frontend/public/catalog/${instance.asset_id}.metadata.json`, import.meta.url), "utf8"));
      for (const contact of meta.contacts_m) {
        const p = new THREE.Vector3(...(contact as [number, number, number])).applyMatrix4(transform);
        assert.ok(Math.abs(p.y - 24.04) < 0.08, instance.asset_id);
      }
    }
  }
  assert.ok(rosters.size > 1);
  assert.equal(aerodromeWorldSpec(0, [], "background").instances.length, 0);
});
