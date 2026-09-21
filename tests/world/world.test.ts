import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import {
  createWorld,
  defaultWorldSpec,
  chunkAddress,
  chunkCoordinates,
  meshChunk,
  chunkPlacements,
} from '../../packages/world/src/index.ts';
import {
  createTerrain,
  PRESETS,
  disposeGroup,
} from '../../frontend/src/terrain.ts';

const digest = (arrays: Float32Array[]) => {
  const h = createHash('sha256');
  for (const a of arrays)
    h.update(new Uint8Array(a.buffer, a.byteOffset, a.byteLength));
  return h.digest('hex');
};
const meshHash = (m: ReturnType<typeof meshChunk>) =>
  digest([m.positions, m.normals, m.colors]);

test('legacy extraction preserves every preset geometry, colors and placement counts', () => {
  const baseline = JSON.parse(
    readFileSync(
      new URL('./legacy-characterization.json', import.meta.url),
      'utf8',
    ),
  );
  for (const p of PRESETS) {
    const t = createTerrain(p.config);
    const mesh = t.group.children[0] as import('three').Mesh;
    assert.deepEqual(
      {
        triangles: t.triangles,
        mesh_sha256: digest(
          ['position', 'normal', 'color'].map(
            (k) => mesh.geometry.getAttribute(k).array as Float32Array,
          ),
        ),
        children: t.group.children.map((c) => [c.name, c.children.length]),
      },
      baseline[p.id],
    );
    disposeGroup(t.group);
  }
});

test('finite world addresses all 256 chunks using floor, including zero and negative boundaries', () => {
  const w = createWorld(defaultWorldSpec(0));
  assert.equal(w.spec.seed, 0);
  const coords = chunkCoordinates(w);
  assert.equal(coords.length, 256);
  assert.deepEqual(coords[0], { x: -8, z: -8 });
  assert.deepEqual(coords.at(-1), { x: 7, z: 7 });
  assert.deepEqual(chunkAddress(-0.01, -128), { x: -1, z: -1 });
  assert.deepEqual(chunkAddress(0, 127.99), { x: 0, z: 0 });
  assert.throws(() => chunkAddress(Infinity, 0), /finite/);
  assert.throws(() => meshChunk(w, { x: -9, z: 0 }), /outside/);
  assert.throws(() => meshChunk(w, { x: 0.5, z: 0 }), /integer/);
});

test('runtime rejects unsupported or undersampled worlds and isolates mutable caller state', () => {
  const spec = defaultWorldSpec();
  assert.throws(() => createWorld({ ...spec, seed: -1 }), /seed/);
  assert.throws(
    () => createWorld({ ...spec, generator_version: 'future' }),
    /generator_version/,
  );
  assert.throws(
    () => createWorld({ ...spec, field_version: 'future' }),
    /field_version/,
  );
  assert.throws(
    () => createWorld({ ...spec, world_id: 'w'.repeat(65) }),
    /world_id/,
  );
  assert.throws(
    () => createWorld({ ...spec, origin_m: [-1000, -32, -1024] }),
    /align/,
  );
  assert.throws(() => createWorld({ ...spec, chunk_size_m: 64 }), /chunk_size/);
  assert.throws(
    () =>
      createWorld({
        ...spec,
        features: [{ ...spec.features[0], type: 'harbor' }],
      }),
    /unsupported/,
  );
  assert.throws(
    () =>
      createWorld({ ...spec, features: [spec.features[0], spec.features[0]] }),
    /duplicate/,
  );
  assert.throws(
    () =>
      createWorld({
        ...spec,
        instances: [{ instance_id: 'x' }],
      } as typeof spec),
    /asset_id/,
  );
  const w = createWorld(spec);
  const before = w.density(0, 40, 0);
  spec.features.length = 0;
  assert.equal(w.density(0, 40, 0), before);
  assert.throws(() => meshChunk(w, { x: 0, z: 0 }, 8), /cell/);
});

test('request order and feature order do not change geometry, normals, colors or placement identities', () => {
  for (const seed of [0, 48291]) {
    const w = createWorld(defaultWorldSpec(seed));
    const coords = [
      { x: -1, z: -1 },
      { x: 0, z: -1 },
      { x: -1, z: 0 },
      { x: 0, z: 0 },
    ];
    const first = new Map(
      coords.map((c) => [
        JSON.stringify(c),
        [meshHash(meshChunk(w, c)), chunkPlacements(w, c)],
      ]),
    );
    const reversed = createWorld({
      ...defaultWorldSpec(seed),
      features: [...defaultWorldSpec(seed).features].reverse(),
    });
    for (const c of coords.reverse())
      assert.deepEqual(
        [meshHash(meshChunk(reversed, c)), chunkPlacements(reversed, c)],
        first.get(JSON.stringify(c)),
      );
    const ids = coords.flatMap((c) => chunkPlacements(w, c).map((p) => p.id));
    assert.equal(new Set(ids).size, ids.length);
  }
  assert.notEqual(
    meshHash(meshChunk(createWorld(defaultWorldSpec(0)), { x: 1, z: 1 })),
    meshHash(meshChunk(createWorld(defaultWorldSpec(1)), { x: 1, z: 1 })),
  );
});

test('default worlds distribute a rich seeded formation layout across the full map', () => {
  const zero = defaultWorldSpec(0);
  const other = defaultWorldSpec(48291);
  assert.ok(zero.features.length >= 12, 'world needs more than four showcase forms');
  assert.equal(zero.features.length, other.features.length);
  for (const type of ['canyon', 'alpine', 'islands', 'coast'])
    assert.ok(
      zero.features.filter((feature) => feature.type === type).length >= 2,
      `world needs multiple ${type} regions`,
    );
  const span = (axis: 0 | 2) => {
    const values = zero.features.map((feature) => feature.center_m[axis]);
    return Math.max(...values) - Math.min(...values);
  };
  assert.ok(span(0) >= 1200, 'formations should span most of world X');
  assert.ok(span(2) >= 1200, 'formations should span most of world Z');
  const changed = zero.features.filter((feature, index) => {
    const next = other.features[index];
    return (
      feature.type !== next.type ||
      feature.center_m.some((value, axis) => value !== next.center_m[axis]) ||
      feature.extent_m.some((value, axis) => value !== next.extent_m[axis])
    );
  });
  assert.ok(
    changed.length >= Math.ceil(zero.features.length * 0.75),
    'seed should visibly change formation layout and scale',
  );
});

test('base terrain has regional elevation and local relief instead of a nearly flat plane', () => {
  for (const seed of [0, 48291, 77123]) {
    const world = createWorld(defaultWorldSpec(seed));
    const heights: number[] = [];
    const localChanges: number[] = [];
    for (let z = -896; z <= 896; z += 64)
      for (let x = -896; x <= 896; x += 64) {
        const height = world.baseHeight(x, z);
        heights.push(height);
        localChanges.push(Math.abs(height - world.baseHeight(x + 24, z + 16)));
      }
    const average = heights.reduce((sum, value) => sum + value, 0) / heights.length;
    const deviation = Math.sqrt(
      heights.reduce((sum, value) => sum + (value - average) ** 2, 0) /
        heights.length,
    );
    const sortedChanges = localChanges.sort((a, b) => a - b);
    assert.ok(Math.max(...heights) - Math.min(...heights) >= 34, `seed ${seed}: regional relief`);
    assert.ok(deviation >= 7, `seed ${seed}: broad terrain variation`);
    assert.ok(
      sortedChanges[Math.floor(sortedChanges.length * 0.75)] >= 2.2,
      `seed ${seed}: local terrain detail`,
    );
  }
});

test('formation seeds produce irregular geometry for every procedural feature family', () => {
  for (const type of ['canyon', 'alpine', 'islands', 'coast'] as const) {
    const spec = defaultWorldSpec(17);
    spec.world_id = `feature-${type}`;
    spec.features = [
      {
        id: `fixture-${type}`,
        type,
        center_m: [64, 40, 64],
        extent_m: [112, 72, 96],
        seed: 101,
      },
    ];
    const first = meshHash(meshChunk(createWorld(spec), { x: 0, z: 0 }));
    spec.features[0].seed = 202;
    const second = meshHash(meshChunk(createWorld(spec), { x: 0, z: 0 }));
    assert.notEqual(first, second, `${type} geometry must respond to its feature seed`);
  }
});

test('world-space decoration includes deterministic trees and rocks on suitable terrain', () => {
  const world = createWorld(defaultWorldSpec(48291));
  const placements = [
    { x: -7, z: -7 },
    { x: -2, z: -2 },
    { x: 1, z: 2 },
    { x: 6, z: 6 },
  ].flatMap((coord) => chunkPlacements(world, coord));
  assert.ok(placements.some((placement) => placement.kind === 'tree'));
  assert.ok(placements.some((placement) => placement.kind === 'rock'));
  assert.equal(new Set(placements.map((placement) => placement.id)).size, placements.length);
  for (const placement of placements) {
    assert.ok(placement.position.every(Number.isFinite));
    assert.ok(placement.scale > 0);
    assert.ok(world.normal(...placement.position)[1] >= 0.72);
  }
});

function boundary(
  m: ReturnType<typeof meshChunk>,
  axis: number,
  value: number,
) {
  const entries = new Map<string, string>();
  for (let i = 0; i < m.positions.length; i += 3)
    if (m.positions[i + axis] === value) {
      const key = Array.from(m.positions.slice(i, i + 3)).join(',');
      const attrs = Array.from(m.normals.slice(i, i + 3))
        .concat(Array.from(m.colors.slice(i, i + 3)))
        .join(',');
      if (entries.has(key)) assert.equal(entries.get(key), attrs);
      entries.set(key, attrs);
    }
  assert.ok(entries.size > 0);
  return [...entries].sort();
}

test('both seam axes match exactly at vertices, gradient normals and biome colors, including a four-chunk arch', () => {
  const w = createWorld(defaultWorldSpec(0));
  const a = meshChunk(w, { x: -1, z: -1 }),
    b = meshChunk(w, { x: 0, z: -1 }),
    c = meshChunk(w, { x: -1, z: 0 });
  assert.deepEqual(boundary(a, 0, 0), boundary(b, 0, 0));
  assert.deepEqual(boundary(a, 2, 0), boundary(c, 2, 0));
  for (const m of [a, b, c]) {
    assert.ok(m.positions.length > 0);
    for (const attr of [m.positions, m.normals, m.colors])
      assert.ok(attr.every(Number.isFinite));
    for (let i = 0; i < m.normals.length; i += 3)
      assert.ok(Math.abs(Math.hypot(...m.normals.slice(i, i + 3)) - 1) < 1e-6);
  }
});

// Independent Moller-Trumbore ray reference, double sided, returns sorted distances.
export function intersections(
  m: ReturnType<typeof meshChunk>,
  o: number[],
  d: number[],
) {
  const hits: number[] = [];
  const p = m.positions;
  const cross = (a: number[], b: number[]) => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
  const dot = (a: number[], b: number[]) =>
    a.reduce((s, v, i) => s + v * b[i], 0);
  for (let i = 0; i < p.length; i += 9) {
    const a = Array.from(p.slice(i, i + 3)),
      e1 = Array.from(p.slice(i + 3, i + 6)).map((v, j) => v - a[j]),
      e2 = Array.from(p.slice(i + 6, i + 9)).map((v, j) => v - a[j]);
    const h = cross(d, e2),
      det = dot(e1, h);
    if (Math.abs(det) < 1e-9) continue;
    const s = o.map((v, j) => v - a[j]),
      u = dot(s, h) / det;
    if (u < 0 || u > 1) continue;
    const q = cross(s, e1),
      v = dot(d, q) / det;
    if (v < 0 || u + v > 1) continue;
    const t = dot(e2, q) / det;
    if (t > 1e-5) hits.push(t);
  }
  return hits
    .sort((a, b) => a - b)
    .filter((t, i, a) => i === 0 || t - a[i - 1] > 1e-4);
}

test('actual triangles retain arch and tunnel passages, an underside and an occluded cavity', () => {
  const spec = defaultWorldSpec(0);
  spec.features = [
    {
      id: 'fixture',
      type: 'canyon',
      center_m: [64, 40, 64],
      extent_m: [112, 72, 80],
      seed: 0,
    },
  ];
  const w = createWorld(spec);
  for (const cellSize of [2, 4]) {
    const m = meshChunk(w, { x: 0, z: 0 }, cellSize);
    assert.equal(
      intersections(m, [64, 38, 0], [0, 0, 1]).length,
      0,
      'arch through ray',
    );
    assert.equal(
      intersections(m, [99.84, 27.04, 0], [0, 0, 1]).length,
      0,
      'tunnel through ray',
    );
    const underside = intersections(m, [106, 20, 96], [0, 1, 0]);
    assert.ok(underside.length >= 2, 'overhang has bottom and top');
    const cavity = [27.6, 34.6, 64];
    assert.ok(w.density(...(cavity as [number, number, number])) < 0);
    for (const d of [
      [1, 0, 0],
      [-1, 0, 0],
      [0, 1, 0],
      [0, -1, 0],
      [0, 0, 1],
      [0, 0, -1],
    ])
      assert.ok(intersections(m, cavity, d).length > 0, 'cavity is enclosed');
    const front = intersections(m, [27.6, 34.6, 0], [0, 0, 1]);
    assert.ok(front.length >= 4, 'front wall occludes interior cavity');
    assert.ok(front[0] < 64 && front[1] < 64 && front[2] > 64);
  }
});

test('continuous base is solid below and has a ray-visible surface throughout negative and positive chunks', () => {
  const w = createWorld(defaultWorldSpec(0));
  for (const c of [
    { x: -8, z: -8 },
    { x: -1, z: 0 },
    { x: 0, z: -1 },
    { x: 7, z: 7 },
  ]) {
    const m = meshChunk(w, c);
    for (let x = 3; x < 128; x += 16)
      for (let z = 5; z < 128; z += 16) {
        const wx = c.x * 128 + x,
          wz = c.z * 128 + z;
        assert.ok(w.density(wx, -31, wz) > 0);
        assert.ok(
          intersections(m, [wx, 95, wz], [0, -1, 0]).length > 0,
          `missing surface ${wx},${wz}`,
        );
      }
  }
});
