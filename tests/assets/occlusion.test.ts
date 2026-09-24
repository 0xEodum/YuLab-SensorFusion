import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as THREE from "three";
import type { AssetRecord } from "@yulab/contracts";
import { buildLidarScene } from "../../packages/sensors/src/lidar.ts";
import { lidarClassId } from "../../packages/sensors/src/lidarClass.ts";

const root = new URL("../../frontend/public/catalog/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("catalog.json", root), "utf8")) as
  { assets: AssetRecord[] };

function sampleTriangle(id: string) {
  const bytes = readFileSync(new URL(`${id}.glb`, root));
  const gltf = JSON.parse(bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString());
  const binaryOffset = 20 + bytes.readUInt32LE(12) + 8;
  for (const mesh of gltf.meshes) for (const primitive of mesh.primitives) {
    const accessor = gltf.accessors[primitive.attributes.POSITION];
    const view = gltf.bufferViews[accessor.bufferView];
    const start = binaryOffset + (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
    for (let i = 0; i < accessor.count; i += 3) {
      const point = (j: number) => new THREE.Vector3(
        bytes.readFloatLE(start + (i + j) * 12),
        bytes.readFloatLE(start + (i + j) * 12 + 4),
        bytes.readFloatLE(start + (i + j) * 12 + 8),
      );
      const a = point(0), b = point(1), c = point(2);
      const normal = b.clone().sub(a).cross(c.clone().sub(a));
      if (normal.length() > 0.1) return { a, b, c, normal: normal.normalize() };
    }
  }
  throw new Error(`${id}: no nondegenerate imported triangle`);
}

test("each catalog GLB has a real first-return and a nearer occluder wins", () => {
  for (const asset of catalog.assets) {
    const { a, b, c, normal } = sampleTriangle(asset.asset_id);
    const center = a.clone().add(b).add(c).divideScalar(3);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute([
      ...a.toArray(), ...b.toArray(), ...c.toArray(),
    ], 3));
    const root = new THREE.Group();
    root.userData = { instance_id: `fixture-${asset.asset_id}`, asset_id: asset.asset_id };
    const surface = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
    surface.name = `${asset.asset_id}-surface`;
    root.add(surface);
    const origin = center.clone().addScaledVector(normal, 2);
    const direction = normal.clone().negate();
    const first = buildLidarScene(root, [asset]);
    const hit = first.first(origin.toArray(), direction.toArray(), 0, 4);
    assert.equal(hit?.instance_id, `fixture-${asset.asset_id}`);
    assert.equal(hit?.class_id, lidarClassId(asset.class_name));
    assert.ok(Math.abs(hit!.range_m - 2) < 1e-4, asset.asset_id);
    first.dispose();

    const blocker = new THREE.Mesh(geometry.clone(), new THREE.MeshBasicMaterial());
    blocker.name = "nearer-occluder";
    blocker.position.copy(normal);
    blocker.userData.lidar_class = "building";
    root.add(blocker);
    const occluded = buildLidarScene(root, [asset]);
    assert.equal(occluded.first(origin.toArray(), direction.toArray(), 0, 4)?.object_name,
      "nearer-occluder", asset.asset_id);
    occluded.dispose();
    geometry.dispose();
    blocker.geometry.dispose();
    (surface.material as THREE.Material).dispose();
    (blocker.material as THREE.Material).dispose();
  }
});
