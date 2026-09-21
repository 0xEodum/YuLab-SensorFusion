import {
  chunkCoordinates,
  type ChunkCoord,
  type Vec3,
  type World,
} from "./field.ts";
import type { ChunkMesh } from "./mesh.ts";
import type { Placement } from "./placement.ts";

export const RESIDENCY_VERSION = "chunk-residency.v1";
export type ChunkData = {
  mesh: ChunkMesh;
  placements: Placement[];
  generationMs: number;
};
export type ChunkGenerator = (
  coord: ChunkCoord,
  pitch: 2 | 4,
  signal: AbortSignal,
) => Promise<ChunkData>;
export const chunkKey = (c: ChunkCoord, pitch: number) =>
  `${c.x},${c.z}@${pitch}`;
export const chunkBytes = (d: ChunkData) =>
  d.mesh.positions.byteLength +
  d.mesh.normals.byteLength +
  d.mesh.colors.byteLength +
  d.placements.length * 256;
export const abortError = () =>
  new DOMException("Chunk request cancelled", "AbortError");

export function displayChunks(
  world: World,
  x: number,
  z: number,
): ChunkCoord[] {
  if (![x, z].every(Number.isFinite))
    throw new Error("Display position must be finite");
  const cx = Math.floor(x / 128),
    cz = Math.floor(z / 128);
  return chunkCoordinates(world).filter(
    (c) => Math.abs(c.x - cx) <= 1 && Math.abs(c.z - cz) <= 1,
  );
}

export type SensorRange = { position: Vec3; range: number };
/** Conservative horizontal range union. No orientation/frustum input is used.
 * Eight metres covers the horizontal reach of every v2 tree/rock, including rotation.
 * Terrain is owned by its triangle's chunk; imported bounds require a new policy. */
export function sensorChunks(
  world: World,
  sensors: SensorRange[],
): ChunkCoord[] {
  if (!sensors.length) throw new Error("At least one sensor is required");
  for (const s of sensors) {
    if (
      s.position.length !== 3 ||
      !Array.from(s.position).every(Number.isFinite) ||
      !Number.isFinite(s.range) ||
      s.range <= 0
    )
      throw new Error("Sensor pose/range must be finite and range positive");
    for (const axis of [0, 2] as const)
      if (
        s.position[axis] < world.spec.origin_m[axis] ||
        s.position[axis] >=
          world.spec.origin_m[axis] + world.spec.extent_m[axis]
      )
        throw new Error("Sensor origin outside finite world");
  }
  return chunkCoordinates(world).filter((c) =>
    sensors.some((s) => {
      const dx = Math.max(
        c.x * 128 - 8 - s.position[0],
        0,
        s.position[0] - ((c.x + 1) * 128 + 8),
      );
      const dz = Math.max(
        c.z * 128 - 8 - s.position[2],
        0,
        s.position[2] - ((c.z + 1) * 128 + 8),
      );
      return dx * dx + dz * dz <= s.range * s.range;
    }),
  );
}

type Entry = { data: ChunkData; bytes: number; pins: number; touched: number };
export type ChunkLease = {
  chunks: ReadonlyMap<string, ChunkData>;
  release: () => void;
};

/** One acquisition at a time per cache. Active leases remain pinned until released.
 * Results are published atomically; cancellation/failure never returns partial residency. */
export class ChunkCache {
  private entries = new Map<string, Entry>();
  private active = false;
  private closed = false;
  private clock = 0;
  private bytes = 0;
  private generate: ChunkGenerator;
  readonly maxChunks: number;
  readonly maxBytes: number;
  readonly stats = {
    generated: 0,
    evicted: 0,
    hits: 0,
    peakBytes: 0,
    peakChunks: 0,
  };
  constructor(
    generate: ChunkGenerator,
    maxChunks = 24,
    maxBytes = 128 * 1024 * 1024,
  ) {
    this.generate = generate;
    this.maxChunks = maxChunks;
    this.maxBytes = maxBytes;
    if (
      !Number.isInteger(maxChunks) ||
      maxChunks < 1 ||
      !Number.isFinite(maxBytes) ||
      maxBytes < 1
    )
      throw new Error("Invalid residency limits");
  }
  snapshot() {
    return {
      ...this.stats,
      chunks: this.entries.size,
      bytes: this.bytes,
      pinned: [...this.entries.values()].filter((e) => e.pins > 0).length,
    };
  }
  private makeRoom(count: number, bytes: number) {
    while (
      this.entries.size + count > this.maxChunks ||
      this.bytes + bytes > this.maxBytes
    ) {
      const victim = [...this.entries]
        .filter(([, e]) => !e.pins)
        .sort((a, b) => a[1].touched - b[1].touched)[0];
      if (!victim)
        throw new Error("Residency budget exceeded by pinned geometry");
      this.entries.delete(victim[0]);
      this.bytes -= victim[1].bytes;
      this.stats.evicted++;
    }
  }
  async acquire(
    coords: ChunkCoord[],
    pitch: 2 | 4,
    signal = new AbortController().signal,
  ): Promise<ChunkLease> {
    if (this.closed) throw new Error("Cache disposed");
    if (this.active) throw new Error("Residency acquisition already running");
    if (pitch !== 2 && pitch !== 4) throw new Error("Unsupported mesh pitch");
    const unique = new Map(coords.map((c) => [chunkKey(c, pitch), c]));
    if (!unique.size || unique.size > this.maxChunks)
      throw new Error("Requested chunks exceed residency capacity");
    this.active = true;
    const held = new Map<string, ChunkData>();
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      for (const key of held.keys()) {
        const e = this.entries.get(key);
        if (e) e.pins--;
      }
    };
    try {
      // Pin cache hits before generating misses so acquisition order cannot evict a hit.
      for (const key of unique.keys()) {
        const e = this.entries.get(key);
        if (e) {
          e.pins++;
          e.touched = ++this.clock;
          held.set(key, e.data);
          this.stats.hits++;
        }
      }
      for (const [key, coord] of unique) {
        if (signal.aborted || this.closed) throw abortError();
        if (held.has(key)) continue;
        // A single in-flight result is outside the retained-cache budget until admission.
        const data = await this.generate(coord, pitch, signal);
        if (signal.aborted || this.closed) throw abortError();
        if (chunkKey(data.mesh.coord, data.mesh.cellSize) !== key)
          throw new Error("Worker returned wrong chunk identity");
        const bytes = chunkBytes(data);
        this.makeRoom(1, bytes);
        this.entries.set(key, { data, bytes, pins: 1, touched: ++this.clock });
        this.bytes += bytes;
        held.set(key, data);
        this.stats.generated++;
        this.stats.peakBytes = Math.max(this.stats.peakBytes, this.bytes);
        this.stats.peakChunks = Math.max(
          this.stats.peakChunks,
          this.entries.size,
        );
      }
      if (signal.aborted || this.closed) throw abortError();
      return { chunks: held, release };
    } catch (error) {
      release();
      throw error;
    } finally {
      this.active = false;
    }
  }
  dispose() {
    this.closed = true;
    this.stats.evicted += this.entries.size;
    this.entries.clear();
    this.bytes = 0;
  }
}

/** Future capture passes execute only inside this lease. Geometry remains pinned
 * through async readback; failures, cancellation and capacity errors block capture. */
export class SensorResidency {
  private world: World;
  private cache: ChunkCache;
  constructor(world: World, cache: ChunkCache) {
    this.world = world;
    this.cache = cache;
  }
  async capture<T>(
    sensors: SensorRange[],
    signal: AbortSignal,
    consume: (chunks: ReadonlyMap<string, ChunkData>) => Promise<T>,
  ): Promise<T> {
    const lease = await this.cache.acquire(
      sensorChunks(this.world, sensors),
      2,
      signal,
    );
    try {
      if (signal.aborted) throw abortError();
      const result = await consume(lease.chunks);
      if (signal.aborted) throw abortError();
      return result;
    } finally {
      lease.release();
    }
  }
}
