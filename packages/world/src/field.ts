import type { WorldSpec } from '@yulab/contracts';
import { validatePayload } from '@yulab/contracts/validate';
import { noise } from './noise.ts';

export const GENERATOR_VERSION = 'connected-world.v1';
export const FIELD_VERSION = 'connected-field.v1';
export const CHUNK_SIZE = 128;
export const MESH_TOLERANCE_M = 0.0001;
export type Vec3 = [number, number, number];
export type Feature = WorldSpec['features'][number];
export type ChunkCoord = { x: number; z: number };
export type World = {
  readonly spec: WorldSpec;
  density: (x: number, y: number, z: number) => number;
  normal: (x: number, y: number, z: number) => Vec3;
  color: (x: number, y: number, z: number, up: number) => Vec3;
  baseHeight: (x: number, z: number) => number;
};

export function defaultWorldSpec(seed = 48291): WorldSpec {
  return {
    schema_version: 'lab.v1',
    kind: 'WorldSpec',
    world_id: `connected-${seed}`,
    seed,
    units: {
      length: 'm',
      temperature: 'K',
      angle: 'rad',
      time: 's',
      world_frame: 'east-up-south',
      matrix_layout: 'row-major',
    },
    origin_m: [-1024, -32, -1024],
    extent_m: [2048, 128, 2048],
    chunk_size_m: CHUNK_SIZE,
    generator_version: GENERATOR_VERSION,
    field_version: FIELD_VERSION,
    features: [
      {
        id: 'central-arch',
        type: 'canyon',
        center_m: [0, 40, 0],
        extent_m: [112, 72, 80],
        seed,
      },
      {
        id: 'northern-ridge',
        type: 'alpine',
        center_m: [-310, 36, -270],
        extent_m: [224, 96, 192],
        seed,
      },
      {
        id: 'island-outcrop',
        type: 'islands',
        center_m: [320, 46, -240],
        extent_m: [112, 64, 96],
        seed,
      },
      {
        id: 'coastal-bluff',
        type: 'coast',
        center_m: [280, 32, 310],
        extent_m: [192, 64, 144],
        seed,
      },
    ],
    instances: [],
  };
}

const clamp = (v: number) => Math.max(0, Math.min(1, v));
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
export function biomeWeight(x: number, z: number, seed: number) {
  return clamp(0.5 + noise(x / 420, 0, z / 420, seed + 71) * 1.2);
}

// Positive means solid. Extents bound each authored feature, in metres.
function featureDensity(f: Feature, wx: number, wy: number, wz: number) {
  const x = (wx - f.center_m[0]) / (f.extent_m[0] / 2);
  const y = (wy - f.center_m[1]) / (f.extent_m[1] / 2);
  const z = (wz - f.center_m[2]) / (f.extent_m[2] / 2);
  const bound = Math.min(1 - Math.abs(x), 1 - Math.abs(y), 1 - Math.abs(z));
  if (bound < -0.05) return (bound * Math.min(...f.extent_m)) / 2;
  const ellipsoid = (
    cx: number,
    cy: number,
    cz: number,
    rx: number,
    ry: number,
    rz: number,
  ) =>
    (1 - Math.hypot((x - cx) / rx, (y - cy) / ry, (z - cz) / rz)) *
    Math.min(rx, ry, rz);
  let d: number;
  if (f.type === 'canyon') {
    const ring = Math.min(
      1 - Math.hypot(x, y),
      0.32 - Math.abs(z),
      (Math.hypot(x / 0.48, (y + 0.18) / 0.66) - 1) * 0.48,
    );
    const right = ellipsoid(0.64, -0.35, 0, 0.36, 0.65, 0.7);
    const left = ellipsoid(-0.65, -0.35, 0, 0.35, 0.65, 0.7);
    const ledge = ellipsoid(0.7, 0.1, 0.54, 0.3, 0.12, 0.43);
    d = Math.max(ring, right, left, ledge);
    // Subtract after union so overlapping rock masses cannot refill openings.
    d = Math.min(
      d,
      (Math.hypot((x - 0.64) / 0.13, (y + 0.36) / 0.18) - 1) * 0.13,
    );
    // Enclosed cavity: the outer wall must occlude its inner surface.
    d = Math.min(d, -ellipsoid(-0.65, -0.15, 0, 0.16, 0.22, 0.24));
  } else if (f.type === 'alpine') {
    d = Math.max(
      ellipsoid(-0.3, -0.15, 0, 0.64, 1, 0.75),
      ellipsoid(0.4, -0.4, 0.2, 0.55, 0.65, 0.6),
    );
    d += noise(wx / 24, wy / 24, wz / 24, f.seed + 3) * 0.06;
  } else if (f.type === 'islands') {
    d = Math.max(
      ellipsoid(-0.4, 0, 0, 0.55, 0.28, 0.7),
      ellipsoid(0.4, 0.4, -0.15, 0.45, 0.3, 0.55),
    );
  } else {
    d = Math.min(
      1 - Math.abs(x),
      0.7 - Math.abs(z),
      0.35 - y + 0.12 * noise(wx / 35, 0, wz / 35, f.seed),
      y + 1,
    );
  }
  return (Math.min(d, bound) * Math.min(...f.extent_m)) / 2;
}

/** Validate the wire boundary, then enforce this generator's narrower supported profile. */
export function createWorld(input: WorldSpec): World {
  validatePayload('WorldSpec', input);
  if (input.generator_version !== GENERATOR_VERSION)
    throw new Error('Unsupported generator_version');
  if (input.field_version !== FIELD_VERSION)
    throw new Error('Unsupported field_version');
  if (input.world_id.length > 64)
    throw new Error('world_id must be at most 64 characters for placement IDs');
  if (input.chunk_size_m !== CHUNK_SIZE)
    throw new Error('chunk_size_m must be 128');
  if (input.origin_m[1] !== -32 || input.extent_m[1] !== 128)
    throw new Error('vertical domain must be [-32,96]');
  for (const axis of [0, 2]) {
    if (input.origin_m[axis] % 128 || input.extent_m[axis] % 128)
      throw new Error('world origin/extent must align to 128 m chunks');
    if (
      input.extent_m[axis] > 2048 ||
      Math.abs(input.origin_m[axis]) > 4096 ||
      Math.abs(input.origin_m[axis] + input.extent_m[axis]) > 4096
    )
      throw new Error('world exceeds verified extent/coordinate limits');
  }
  if (input.instances.length)
    throw new Error('asset instances are unsupported until SF-04');
  const ids = new Set<string>();
  for (const f of input.features) {
    if (!['canyon', 'alpine', 'islands', 'coast'].includes(f.type))
      throw new Error(`unsupported feature type: ${f.type}`);
    if (ids.has(f.id)) throw new Error(`duplicate feature id: ${f.id}`);
    ids.add(f.id);
    for (let axis = 0; axis < 3; axis++) {
      if (f.extent_m[axis] < 64 || f.extent_m[axis] > 256)
        throw new Error(
          `feature ${f.id}: extent must be 64..256 m to resolve geometry`,
        );
      const lo = f.center_m[axis] - f.extent_m[axis] / 2,
        hi = f.center_m[axis] + f.extent_m[axis] / 2;
      if (
        lo < input.origin_m[axis] ||
        hi > input.origin_m[axis] + input.extent_m[axis] ||
        (axis === 1 && (lo < -24 || hi > 88))
      )
        throw new Error(`feature ${f.id}: bounds exceed field domain`);
    }
  }
  // Snapshot, canonical feature ordering and recursive freezing prevent load-order mutation.
  const spec = structuredClone(input);
  spec.features.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  function freeze(value: object) {
    for (const v of Object.values(value))
      if (v && typeof v === 'object') freeze(v);
    Object.freeze(value);
  }
  freeze(spec);
  const baseHeight = (x: number, z: number) =>
    12 +
    noise(x / 260, 0, z / 260, spec.seed) * 7 +
    noise(x / 65, 0, z / 65, spec.seed + 11) * 2;
  const density = (x: number, y: number, z: number) => {
    let d = baseHeight(x, z) - y;
    for (const f of spec.features) d = Math.max(d, featureDensity(f, x, y, z));
    return d;
  };
  const normal = (x: number, y: number, z: number): Vec3 => {
    const h = 0.05;
    const a = density(x - h, y, z) - density(x + h, y, z),
      b = density(x, y - h, z) - density(x, y + h, z),
      c = density(x, y, z - h) - density(x, y, z + h);
    const len = Math.hypot(a, b, c);
    return len > 1e-12 ? [a / len, b / len, c / len] : [0, 1, 0];
  };
  const color = (x: number, y: number, z: number, up: number): Vec3 => {
    const biome = biomeWeight(x, z, spec.seed);
    const grass = clamp((up - 0.45) / 0.35) * clamp((38 - y) / 14);
    // Linear RGB; both biome and slope transitions are continuous in world space.
    const stone: Vec3 = [
      mix(0.48, 0.35, biome),
      mix(0.31, 0.38, biome),
      mix(0.18, 0.36, biome),
    ];
    const green: Vec3 = [
      mix(0.26, 0.15, biome),
      mix(0.31, 0.25, biome),
      mix(0.12, 0.16, biome),
    ];
    const shade = 0.96 + 0.04 * noise(x / 12, y / 12, z / 12, spec.seed + 19);
    return stone.map((v, i) => mix(v, green[i], grass) * shade) as Vec3;
  };
  return Object.freeze({ spec, density, normal, color, baseHeight });
}

export function chunkAddress(x: number, z: number): ChunkCoord {
  if (!Number.isFinite(x) || !Number.isFinite(z))
    throw new Error('chunk coordinates must be finite');
  return { x: Math.floor(x / 128), z: Math.floor(z / 128) };
}
export function assertChunk(w: World, c: ChunkCoord) {
  if (!Number.isInteger(c.x) || !Number.isInteger(c.z))
    throw new Error('chunk address must be integer');
  const s = w.spec;
  if (
    c.x * 128 < s.origin_m[0] ||
    c.z * 128 < s.origin_m[2] ||
    (c.x + 1) * 128 > s.origin_m[0] + s.extent_m[0] ||
    (c.z + 1) * 128 > s.origin_m[2] + s.extent_m[2]
  )
    throw new Error('chunk outside world extent');
}
export function chunkCoordinates(w: World): ChunkCoord[] {
  const result: ChunkCoord[] = [];
  const s = w.spec;
  for (
    let x = s.origin_m[0] / 128;
    x < (s.origin_m[0] + s.extent_m[0]) / 128;
    x++
  )
    for (
      let z = s.origin_m[2] / 128;
      z < (s.origin_m[2] + s.extent_m[2]) / 128;
      z++
    )
      result.push({ x, z });
  return result;
}
