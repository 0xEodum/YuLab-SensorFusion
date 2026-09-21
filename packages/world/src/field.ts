import type { WorldSpec } from '@yulab/contracts';
import { validatePayload } from '@yulab/contracts/validate';
import { hash, noise } from './noise.ts';

export const GENERATOR_VERSION = 'connected-world.v2';
export const FIELD_VERSION = 'connected-field.v2';
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

const clamp = (v: number) => Math.max(0, Math.min(1, v));
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const seeded = (cell: number, channel: number, seed: number) =>
  hash(cell, channel, cell * 17 + channel * 31, seed);

/** Multi-scale, domain-warped height shared by specs, fields and QA metrics. */
export function terrainHeight(x: number, z: number, seed: number) {
  const warpX = noise(x / 410, 0, z / 410, seed + 101) * 105;
  const warpZ = noise(x / 410, 7, z / 410, seed + 103) * 105;
  const broad = noise((x + warpX) / 510, 0, (z + warpZ) / 510, seed) * 15;
  const ridgeSignal = noise((x - warpZ) / 235, 3, (z + warpX) / 235, seed + 7);
  const ridges = (1 - Math.abs(ridgeSignal)) ** 2 * 10 - 3;
  const hills =
    noise((x + warpX * 0.4) / 112, 11, (z + warpZ * 0.4) / 112, seed + 11) *
    9.5;
  const detail = noise(x / 34, 19, z / 34, seed + 29) * 4.5;
  return Math.max(2, Math.min(58, 19 + broad + ridges + hills + detail));
}

export function defaultWorldSpec(seed = 48291): WorldSpec {
  const featureTypes = ['canyon', 'alpine', 'islands', 'coast'] as const;
  const rotation = Math.floor(seeded(0, 80, seed) * featureTypes.length);
  const features: WorldSpec['features'] = [];
  for (let row = 0; row < 4; row++)
    for (let column = 0; column < 4; column++) {
      const cell = row * 4 + column;
      const x = -768 + column * 512 + (seeded(cell, 1, seed) - 0.5) * 210;
      const z = -768 + row * 512 + (seeded(cell, 2, seed) - 0.5) * 210;
      const type = featureTypes[(cell + rotation) % featureTypes.length];
      const width =
        (type === 'alpine' || type === 'coast' ? 176 : 120) +
        seeded(cell, 3, seed) * (type === 'alpine' ? 64 : 48);
      const depth =
        (type === 'alpine' || type === 'coast' ? 160 : 112) +
        seeded(cell, 4, seed) * 56;
      const height =
        (type === 'alpine' ? 88 : type === 'canyon' ? 72 : 64) +
        seeded(cell, 5, seed) * (type === 'alpine' ? 8 : 16);
      const ground = terrainHeight(x, z, seed);
      const centerY = Math.min(
        88 - height / 2,
        Math.max(-24 + height / 2, ground + height * 0.2),
      );
      features.push({
        id: `region-${row}-${column}`,
        type,
        center_m: [x, centerY, z],
        extent_m: [width, height, depth],
        seed: Math.floor(seeded(cell, 6, seed) * 0x100000000),
      });
    }
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
    features,
    instances: [],
  };
}

export function biomeWeight(x: number, z: number, seed: number) {
  const warpedX = x + noise(x / 500, 5, z / 500, seed + 73) * 90;
  const warpedZ = z + noise(x / 500, 9, z / 500, seed + 79) * 90;
  return clamp(0.5 + noise(warpedX / 360, 0, warpedZ / 360, seed + 71) * 1.15);
}

// Positive means solid. Extents bound each authored feature, in metres.
function featureDensity(f: Feature, wx: number, wy: number, wz: number) {
  const localX = wx - f.center_m[0],
    localY = wy - f.center_m[1],
    localZ = wz - f.center_m[2];
  const warp = noise(wx / 31, wy / 37, wz / 31, f.seed + 31);
  const crossWarp = noise(wx / 19, wy / 23, wz / 19, f.seed + 37);
  const x = (localX + warp * f.extent_m[0] * 0.055) / (f.extent_m[0] / 2);
  const y = (localY + crossWarp * f.extent_m[1] * 0.035) / (f.extent_m[1] / 2);
  const z =
    (localZ + (warp - crossWarp) * f.extent_m[2] * 0.04) / (f.extent_m[2] / 2);
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
  const coarse = noise(wx / 24, wy / 21, wz / 24, f.seed + 3) * 0.085;
  const fine = noise(wx / 9, wy / 11, wz / 9, f.seed + 13) * 0.028;
  const strata =
    Math.sin(
      (wy - f.center_m[1]) * 0.42 + noise(wx / 35, 0, wz / 35, f.seed + 17) * 2,
    ) * 0.018;
  const surface = coarse + fine + strata;
  let d: number;
  if (f.type === 'canyon') {
    const ring = Math.min(
      1 - Math.hypot(x, y),
      0.32 - Math.abs(z),
      (Math.hypot(x / 0.48, (y + 0.18) / 0.66) - 1) * 0.48,
    );
    const right = ellipsoid(0.64, -0.35, 0, 0.38, 0.68, 0.72);
    const left = ellipsoid(-0.65, -0.35, 0, 0.37, 0.68, 0.72);
    const ledge = ellipsoid(0.7, 0.08, 0.52, 0.34, 0.14, 0.46);
    const shoulder = ellipsoid(-0.2, 0.16, -0.34, 0.55, 0.22, 0.42);
    d = Math.max(ring, right, left, ledge, shoulder) + surface;
    // Subtract after union so overlapping rock masses cannot refill openings.
    d = Math.min(
      d,
      (Math.hypot((x - 0.64) / 0.13, (y + 0.36) / 0.18) - 1) * 0.13,
    );
    // Enclosed cavity: the outer wall must occlude its inner surface.
    d = Math.min(d, -ellipsoid(-0.65, -0.15, 0, 0.16, 0.22, 0.24));
  } else if (f.type === 'alpine') {
    const peakShift = (seeded(f.seed & 0xffff, 41, f.seed) - 0.5) * 0.18;
    d = Math.max(
      ellipsoid(-0.36 + peakShift, -0.05, -0.08, 0.5, 1.05, 0.58),
      ellipsoid(0.28, -0.3, 0.24 - peakShift, 0.58, 0.82, 0.56),
      ellipsoid(0.04, -0.52, -0.42, 0.7, 0.48, 0.5),
    );
    d += surface * 1.35;
  } else if (f.type === 'islands') {
    d =
      Math.max(
        ellipsoid(-0.42, 0.02, 0.04, 0.58, 0.3, 0.7),
        ellipsoid(0.36, 0.38, -0.16, 0.46, 0.34, 0.58),
        ellipsoid(0.08, -0.38, 0.42, 0.34, 0.22, 0.4),
      ) +
      surface * 1.15;
  } else {
    const edge = x + 0.28 + noise(wx / 29, 0, wz / 29, f.seed + 43) * 0.18;
    const cap = 0.34 - y + noise(wx / 21, 0, wz / 21, f.seed + 47) * 0.08;
    const bluff = Math.min(edge, cap, y + 0.95, 1 - Math.abs(z));
    const stacks = Math.max(
      ellipsoid(-0.42, -0.2, 0.38, 0.34, 0.55, 0.3),
      ellipsoid(-0.3, -0.34, -0.4, 0.3, 0.42, 0.27),
    );
    d = Math.min(Math.max(bluff, stacks) + surface, bound);
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
  const baseHeight = (x: number, z: number) => terrainHeight(x, z, spec.seed);
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
    const grass = clamp((up - 0.38) / 0.4) * clamp((48 - y) / 22);
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
    const strataTone =
      Math.sin(y * 0.48 + noise(x / 30, 0, z / 30, spec.seed + 23) * 2) * 0.035;
    const shade =
      0.91 + 0.1 * noise(x / 10, y / 12, z / 10, spec.seed + 19) + strataTone;
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
