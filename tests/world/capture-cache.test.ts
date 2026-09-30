import assert from "node:assert/strict";
import test from "node:test";
import { CaptureGeometryCache } from "../../workers/capture/geometry.ts";
import { defaultWorldSpec, type ChunkData } from "../../packages/world/src/index.ts";

const generate = (_world: unknown, coord: { x: number; z: number }): ChunkData => ({
  mesh: { coord, cellSize: 2, positions: new Float32Array(9),
    normals: new Float32Array(9), colors: new Float32Array(9) },
  placements: [], generationMs: 0,
});

test("capture cache reuses exact snapshots and invalidates changed world contents", () => {
  const cache = new CaptureGeometryCache(2, 1024, generate);
  const spec = defaultWorldSpec(0);
  cache.useWorld(spec);
  const first = cache.chunk({ x: 0, z: 0 });
  cache.useWorld(structuredClone(spec));
  assert.equal(cache.chunk({ x: 0, z: 0 }), first);
  const changed = structuredClone(spec);
  changed.features[0].seed++;
  cache.useWorld(changed); // Same world_id and seed; different authoritative geometry.
  assert.notEqual(cache.chunk({ x: 0, z: 0 }), first);
  assert.equal(cache.snapshot().hits, 1);
});

test("capture cache respects LRU count and byte budgets without rejecting large captures", () => {
  const cache = new CaptureGeometryCache(2, 216, generate);
  cache.useWorld(defaultWorldSpec(0));
  const first = cache.chunk({ x: -1, z: 0 });
  cache.chunk({ x: 0, z: 0 });
  assert.equal(cache.chunk({ x: -1, z: 0 }), first);
  cache.chunk({ x: 1, z: 0 });
  assert.equal(cache.snapshot().chunks, 2);
  assert.equal(cache.snapshot().bytes, 216);
  cache.chunk({ x: 0, z: 0 });
  assert.equal(cache.snapshot().generated, 4);
  const small = new CaptureGeometryCache(2, 1, generate);
  small.useWorld(defaultWorldSpec(0));
  assert.equal(small.chunk({ x: 0, z: 0 }).mesh.positions.length, 9);
  assert.equal(small.snapshot().bytes, 0);
});
