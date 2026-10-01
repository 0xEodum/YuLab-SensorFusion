import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import { buildLidarScene, LidarGeometryCache } from "../../packages/sensors/src/lidar.ts";
import { createWorld, defaultWorldSpec, meshChunk } from "../../packages/world/src/index.ts";

function scene(positions: Float32Array, normals: Float32Array) {
  const root = new THREE.Group();
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
  root.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial()));
  // Indexed primitive: built in place per scan, never cached.
  const rock = new THREE.Mesh(new THREE.BoxGeometry(3, 3, 3), new THREE.MeshStandardMaterial());
  rock.position.set(-60, 30, -60);
  root.add(rock);
  return { root, geometry };
}

function rays(lidar: ReturnType<typeof buildLidarScene>) {
  const hits = [];
  for (let i = 0; i < 400; i++) {
    const a = (i / 400) * Math.PI * 2, e = -0.15 - (i % 7) * 0.08;
    hits.push(lidar.first([-64, 60, -64],
      [Math.cos(e) * Math.cos(a), Math.sin(e), Math.cos(e) * Math.sin(a)], 0.5, 400));
  }
  return hits;
}

test("cached LiDAR BVHs give identical returns and never index rendered geometry", () => {
  const mesh = meshChunk(createWorld(defaultWorldSpec(48291)), { x: -1, z: -1 }, 4);
  const reference = buildLidarScene(scene(mesh.positions, mesh.normals).root);
  const expected = rays(reference);
  reference.dispose();
  assert.ok(expected.some((hit) => hit !== null));

  const cache = new LidarGeometryCache();
  for (let pass = 0; pass < 2; pass++) {
    // Fresh render geometry around the same immutable arrays, as per capture.
    const { root, geometry } = scene(mesh.positions, mesh.normals);
    const lidar = buildLidarScene(root, [], cache);
    assert.deepEqual(rays(lidar), expected);
    assert.equal(geometry.index, null);
    lidar.dispose();
  }
  assert.deepEqual(cache.stats, { hits: 1, built: 1 });
});
