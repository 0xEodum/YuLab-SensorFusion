import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";
import type { AssetRecord } from "@yulab/contracts";
import { AssetTemplateCache } from "../../packages/assets/src/index.ts";

const id = (m: THREE.Material) => (m as unknown as { id: number }).id;
const record = (sha: string) => ({ asset_id: "f16", content_sha256: sha }) as AssetRecord;

function template() {
  const createdFirst = new THREE.MeshStandardMaterial({ color: 0x222222 });
  const createdSecond = new THREE.MeshStandardMaterial({ color: 0x111111 });
  const group = new THREE.Group();
  // Traversal meets the later-created material first.
  group.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), createdSecond));
  group.add(new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), createdFirst));
  group.add(new THREE.Mesh(new THREE.BoxGeometry(3, 3, 3), createdSecond));
  return group;
}

const meshes = (group: THREE.Object3D) =>
  group.children.filter((o): o is THREE.Mesh => o instanceof THREE.Mesh);

test("cached templates are keyed by content hash and handed out as independent copies", () => {
  const cache = new AssetTemplateCache();
  const source = template();
  cache.retain(record("a"), source);
  assert.equal(cache.take(record("b")), null);
  const first = cache.take(record("a"))!, second = cache.take(record("a"))!;
  assert.deepEqual(cache.stats, { hits: 2, loaded: 1 });
  for (const [a, b, s] of meshes(first).map((m, i) => [m, meshes(second)[i], meshes(source)[i]])) {
    assert.notEqual(a.geometry, b.geometry);
    // Vertex data is immutable and shared; geometry objects and indices are per copy.
    assert.equal(a.geometry.getAttribute("position"), b.geometry.getAttribute("position"));
    assert.deepEqual(a.geometry.getAttribute("position").array, s.geometry.getAttribute("position").array);
    assert.notEqual(a.geometry.index, b.geometry.index);
    assert.notEqual(a.material, b.material);
    assert.notEqual(a.material, s.material);
  }
  // A scene that indexes or mutates its copy cannot affect later copies.
  meshes(first)[0].geometry.setIndex([0, 1, 2]);
  assert.equal(cache.take(record("a"))!.children.length, 3);
  assert.deepEqual(meshes(cache.take(record("a"))!)[0].geometry.index!.array,
    meshes(source)[0].geometry.index!.array);
});

test("copies keep shared materials shared and clone them in creation order", () => {
  const cache = new AssetTemplateCache();
  cache.retain(record("a"), template());
  const copy = meshes(cache.take(record("a"))!);
  assert.equal(copy[0].material, copy[2].material);
  const unique = [...new Set(copy.map((m) => m.material as THREE.Material))];
  const colors = unique.slice().sort((a, b) => id(a) - id(b))
    .map((m) => (m as THREE.MeshStandardMaterial).color.getHex());
  assert.deepEqual(colors, [0x222222, 0x111111]);
});
