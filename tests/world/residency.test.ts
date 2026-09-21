import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import {
  createWorld,
  defaultWorldSpec,
  meshChunk,
  chunkPlacements,
  ChunkCache,
  SensorResidency,
  sensorChunks,
  displayChunks,
  chunkKey,
  validateBookmark,
  type ChunkData,
  type ChunkGenerator,
  type ChunkCoord,
} from "../../packages/world/src/index.ts";

const world = createWorld(defaultWorldSpec(0));
const fake: ChunkGenerator = async (coord, pitch) => ({
  mesh: {
    coord,
    cellSize: pitch,
    positions: new Float32Array(9),
    normals: new Float32Array(9),
    colors: new Float32Array(9),
  },
  placements: [],
  generationMs: 1,
});
const deferred = <T>() => {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

test("bounded LRU keeps active leases pinned through 110 boundary transitions and releases all data", async () => {
  const cache = new ChunkCache(fake, 24, 24 * 108);
  let lease = await cache.acquire(displayChunks(world, -832, -832), 4);
  for (let i = 0; i < 110; i++) {
    const x = -6 + (i % 12),
      z = -6 + (Math.floor(i / 12) % 12);
    const coords = displayChunks(world, x * 128 + 64, z * 128 + 64);
    const next = await cache.acquire(coords, 4);
    assert.deepEqual(
      [...next.chunks.keys()].sort(),
      coords.map((c) => chunkKey(c, 4)).sort(),
    );
    lease.release();
    lease = next;
    assert.ok(cache.snapshot().chunks <= 24);
    assert.ok(cache.snapshot().bytes <= 24 * 108);
    assert.equal(cache.snapshot().pinned, 9);
  }
  assert.ok(cache.stats.evicted > 100);
  assert.ok(cache.stats.hits > 100);
  lease.release();
  lease.release();
  assert.equal(cache.snapshot().pinned, 0);
  cache.dispose();
  assert.equal(cache.snapshot().bytes, 0);
  assert.equal(cache.snapshot().chunks, 0);
  await assert.rejects(cache.acquire([{ x: 0, z: 0 }], 4), /disposed/);
});

test("cancellation discards late generation, preserves displayed lease, and allows retry", async () => {
  const delayed = deferred<ChunkData>();
  let calls = 0;
  const cache = new ChunkCache(async (c, p, s) =>
    ++calls === 2 ? delayed.promise : fake(c, p, s),
  );
  const old = await cache.acquire([{ x: 0, z: 0 }], 4);
  const abort = new AbortController(),
    pending = cache.acquire([{ x: 1, z: 0 }], 4, abort.signal);
  abort.abort();
  delayed.resolve(await fake({ x: 1, z: 0 }, 4, abort.signal));
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(cache.snapshot().chunks, 1);
  assert.equal(cache.snapshot().pinned, 1);
  const next = await cache.acquire([{ x: 2, z: 0 }], 4);
  next.release();
  old.release();
  assert.equal(cache.snapshot().pinned, 0);
});

test("capacity, failed generation and wrong identity never expose a partial capture", async () => {
  const signal = new AbortController().signal;
  for (const cache of [
    new ChunkCache(fake, 1),
    new ChunkCache(fake, 24, 1),
    new ChunkCache(async () => {
      throw new Error("worker failure");
    }),
    new ChunkCache((_, p, s) => fake({ x: 7, z: 7 }, p, s)),
  ]) {
    let consumed = false;
    await assert.rejects(
      new SensorResidency(world, cache).capture(
        [{ position: [127, 80, 64], range: 50 }],
        signal,
        async () => {
          consumed = true;
        },
      ),
    );
    assert.equal(consumed, false);
    assert.equal(cache.snapshot().pinned, 0);
    cache.dispose();
  }
});

test("range union includes off-frustum and cross-boundary occluders, negative chunks and protruding placements", () => {
  const coords = sensorChunks(world, [{ position: [127, 50, 64], range: 1 }]);
  assert.ok(coords.some((c) => c.x === 1 && c.z === 0));
  assert.ok(
    sensorChunks(world, [{ position: [124, 50, 64], range: 1 }]).some(
      (c) => c.x === 1,
    ),
  );
  assert.ok(
    sensorChunks(world, [{ position: [-0.1, 50, -0.1], range: 1 }]).some(
      (c) => c.x === -1 && c.z === -1,
    ),
  );
  const union = sensorChunks(world, [
    { position: [-500, 50, -500], range: 30 },
    { position: [500, 50, 500], range: 30 },
  ]);
  assert.ok(union.some((c) => c.x < 0));
  assert.ok(union.some((c) => c.x > 0));
  for (const range of [0, -1, NaN, Infinity])
    assert.throws(
      () => sensorChunks(world, [{ position: [0, 0, 0], range }]),
      /range/,
    );
  assert.throws(
    () => sensorChunks(world, [{ position: [1024, 0, 0], range: 1 }]),
    /outside/,
  );
  assert.throws(() => sensorChunks(world, []), /sensor/);
});

test("capture waits for final occluder and pins geometry through asynchronous readback", async () => {
  const gate = deferred<ChunkData>(),
    readback = deferred<void>();
  const coords = sensorChunks(world, [{ position: [127, 80, 64], range: 20 }]);
  const last = coords.at(-1)!;
  const reached = deferred<void>();
  const cache = new ChunkCache(async (c, p, s) => {
    if (c.x === last.x && c.z === last.z) {
      reached.resolve();
      return gate.promise;
    }
    return fake(c, p, s);
  });
  let consumed = false;
  const capture = new SensorResidency(world, cache).capture(
    [{ position: [127, 80, 64], range: 20 }],
    new AbortController().signal,
    async (chunks) => {
      consumed = true;
      assert.equal(chunks.size, coords.length);
      assert.equal(cache.snapshot().pinned, coords.length);
      await readback.promise;
    },
  );
  await reached.promise;
  assert.equal(consumed, false);
  gate.resolve(await fake(last, 2, new AbortController().signal));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(consumed, true);
  assert.equal(cache.snapshot().pinned, coords.length);
  readback.resolve();
  await capture;
  assert.equal(cache.snapshot().pinned, 0);
});

test("real sensor triangles block a ray across the display boundary behind a west-facing display", async () => {
  // The display fixture contains only chunk 0,0 and looks west. The ray travels east
  // across x=128 then downward, hitting terrain that display residency cannot supply.
  const generate: ChunkGenerator = async (c, pitch) => ({
    mesh: meshChunk(world, c, pitch),
    placements: chunkPlacements(world, c),
    generationMs: 0,
  });
  const cache = new ChunkCache(generate);
  await new SensorResidency(world, cache).capture(
    [{ position: [127.9, 80, 64], range: 90 }],
    new AbortController().signal,
    async (chunks) => {
      const ray = new THREE.Raycaster(
        new THREE.Vector3(127.9, 80, 64),
        new THREE.Vector3(1, -20, 0).normalize(),
        0,
        90,
      );
      const hits: { distance: number; coord: ChunkCoord }[] = [];
      for (const data of chunks.values()) {
        assert.equal(data.mesh.cellSize, 2);
        const geometry = new THREE.BufferGeometry().setAttribute(
          "position",
          new THREE.BufferAttribute(data.mesh.positions, 3),
        );
        const material = new THREE.MeshBasicMaterial({
          side: THREE.DoubleSide,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.updateMatrixWorld();
        for (const hit of ray.intersectObject(mesh))
          hits.push({ distance: hit.distance, coord: data.mesh.coord });
        geometry.dispose();
        material.dispose();
      }
      hits.sort((a, b) => a.distance - b.distance);
      assert.ok(hits.length);
      assert.deepEqual(hits[0].coord, { x: 1, z: 0 });
    },
  );
  cache.dispose();
});

test("bookmark validation isolates the pose and rejects mismatched world, units and corrupt values", () => {
  const b = {
    version: "rig-bookmark.v1",
    name: "North",
    world: world.spec,
    position: [0, 80, 0],
    quaternion: [0, 0, 0, 1],
    target: [0, 20, -30],
    navigation: "flight",
    pitch: 4,
  };
  const saved = validateBookmark(b, world.spec);
  b.position[0] = 50;
  assert.equal(saved.position[0], 0);
  for (const bad of [
    { ...b, version: "v2" },
    { ...b, quaternion: [0, 0, 0, 0] },
    { ...b, position: [Infinity, 0, 0] },
    { ...b, position: new Array(3) },
    { ...b, quaternion: new Array(4) },
    { ...b, position: [1024, 0, 0] },
    { ...b, world: defaultWorldSpec(1) },
  ])
    assert.throws(() => validateBookmark(bad, world.spec));
});

test("consumer failure and cancellation during readback release leases without successful publication", async () => {
  const cache = new ChunkCache(fake),
    residency = new SensorResidency(world, cache);
  const ranges = [
    { position: [127, 80, 64] as [number, number, number], range: 20 },
  ];
  await assert.rejects(
    residency.capture(ranges, new AbortController().signal, async () => {
      throw new Error("readback failed");
    }),
    /readback failed/,
  );
  assert.equal(cache.snapshot().pinned, 0);
  const signal = new AbortController(),
    entered = deferred<void>(),
    finish = deferred<void>();
  const pending = residency.capture(ranges, signal.signal, async () => {
    entered.resolve();
    await finish.promise;
    return "not publishable";
  });
  await entered.promise;
  signal.abort();
  assert.ok(cache.snapshot().pinned > 0);
  finish.resolve();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(cache.snapshot().pinned, 0);
});
