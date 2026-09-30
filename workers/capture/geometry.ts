import type { WorldSpec } from "@yulab/contracts";
import { createWorld, meshChunk, chunkPlacements, chunkBytes,
  type ChunkCoord, type ChunkData, type World } from "@yulab/world";

/** Retain only deterministic CPU geometry. Sensor state and GPU objects are per capture. */
export class CaptureGeometryCache {
  private key = "";
  private world: World | null = null;
  private entries = new Map<string, ChunkData>();
  private bytes = 0;
  readonly stats = { hits: 0, generated: 0, evicted: 0 };
  readonly maxChunks: number;
  readonly maxBytes: number;
  private generate: (world: World, coord: ChunkCoord) => ChunkData;
  constructor(maxChunks = 64, maxBytes = 128 * 1024 * 1024,
    generate = (world: World, coord: ChunkCoord): ChunkData => ({
      mesh: meshChunk(world, coord, 2), placements: chunkPlacements(world, coord), generationMs: 0,
    })) {
    if (!Number.isInteger(maxChunks) || maxChunks < 1 || !Number.isFinite(maxBytes) || maxBytes < 1)
      throw new Error("Invalid capture cache budget");
    this.maxChunks = maxChunks;
    this.maxBytes = maxBytes;
    this.generate = generate;
  }
  useWorld(spec: WorldSpec): World {
    // Do not trust the caller's world ID/hash as a cache key. Include the complete snapshot.
    const key = JSON.stringify(spec);
    if (key !== this.key || !this.world) {
      this.stats.evicted += this.entries.size;
      this.entries.clear();
      this.bytes = 0;
      this.world = createWorld(spec);
      this.key = key;
    }
    return this.world;
  }
  chunk(coord: ChunkCoord): ChunkData {
    if (!this.world) throw new Error("Capture cache requires a world snapshot");
    const key = `${coord.x},${coord.z}@2`;
    const hit = this.entries.get(key);
    if (hit) {
      this.entries.delete(key);
      this.entries.set(key, hit);
      this.stats.hits++;
      return hit;
    }
    const data = this.generate(this.world, coord);
    this.stats.generated++;
    const bytes = chunkBytes(data);
    // Oversized captures remain supported; only retained data is bounded.
    if (bytes <= this.maxBytes) {
      while (this.entries.size >= this.maxChunks || this.bytes + bytes > this.maxBytes) {
        const [oldKey, old] = this.entries.entries().next().value!;
        this.entries.delete(oldKey);
        this.bytes -= chunkBytes(old);
        this.stats.evicted++;
      }
      this.entries.set(key, data);
      this.bytes += bytes;
    }
    return data;
  }
  snapshot() { return { ...this.stats, chunks: this.entries.size, bytes: this.bytes }; }
}
