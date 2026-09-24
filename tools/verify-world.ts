import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import {
  createWorld,
  defaultWorldSpec,
  aerodromeWorldSpec,
  harborWorldSpec,
  chunkCoordinates,
  meshChunk,
  chunkPlacements,
  type ChunkMesh,
} from "../packages/world/src/index.ts";

const sha = (data: string | ArrayBufferView) =>
  createHash("sha256")
    .update(
      typeof data === "string"
        ? data
        : new Uint8Array(data.buffer, data.byteOffset, data.byteLength),
    )
    .digest("hex");
const key = (x: number, z: number) => `${x},${z}`;
function inspect(m: ChunkMesh, minHeight = 0) {
  const p = m.positions,
    ox = m.coord.x * 128,
    oz = m.coord.z * 128;
  const sides = [
    new Map<string, string>(),
    new Map<string, string>(),
    new Map<string, string>(),
    new Map<string, string>(),
  ];
  const edges = new Map<
    string,
    { a: number[]; b: number[]; count: number; orientation: number }
  >();
  const top = new Float64Array(32 * 32).fill(-Infinity);
  for (let i = 0; i < p.length; i += 9) {
    const tri = [
      Array.from(p.slice(i, i + 3)),
      Array.from(p.slice(i + 3, i + 6)),
      Array.from(p.slice(i + 6, i + 9)),
    ];
    for (let v = 0; v < 3; v++) {
      const a = tri[v],
        b = tri[(v + 1) % 3],
        ak = a.join(","),
        bk = b.join(",");
      const ek = ak < bk ? `${ak}|${bk}` : `${bk}|${ak}`;
      const entry = edges.get(ek) ?? { a, b, count: 0, orientation: 0 };
      entry.count++;
      entry.orientation += ak < bk ? 1 : -1;
      edges.set(ek, entry);
      for (let s = 0; s < 4; s++)
        if (a[s < 2 ? 0 : 2] === [ox, ox + 128, oz, oz + 128][s]) {
          const off = i + v * 3;
          const attrs = Array.from(m.normals.slice(off, off + 3))
            .concat(Array.from(m.colors.slice(off, off + 3)))
            .join(",");
          assert.ok(
            !sides[s].has(ak) || sides[s].get(ak) === attrs,
            "inconsistent duplicate attributes",
          );
          sides[s].set(ak, attrs);
        }
    }
    // Rasterize upward triangles onto independent vertical probes, one per 4 m cell.
    const [a, b, c] = tri;
    const den = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2]);
    if (Math.abs(den) < 1e-12) continue;
    const minX = Math.max(0, Math.floor((Math.min(a[0], b[0], c[0]) - ox) / 4));
    const maxX = Math.min(
      31,
      Math.floor((Math.max(a[0], b[0], c[0]) - ox) / 4),
    );
    const minZ = Math.max(0, Math.floor((Math.min(a[2], b[2], c[2]) - oz) / 4));
    const maxZ = Math.min(
      31,
      Math.floor((Math.max(a[2], b[2], c[2]) - oz) / 4),
    );
    for (let x = minX; x <= maxX; x++)
      for (let z = minZ; z <= maxZ; z++) {
        const px = ox + (x + 0.37) * 4,
          pz = oz + (z + 0.61) * 4;
        const u =
          ((b[2] - c[2]) * (px - c[0]) + (c[0] - b[0]) * (pz - c[2])) / den;
        const v =
          ((c[2] - a[2]) * (px - c[0]) + (a[0] - c[0]) * (pz - c[2])) / den;
        if (u >= -1e-8 && v >= -1e-8 && u + v <= 1 + 1e-8)
          top[x + z * 32] = Math.max(
            top[x + z * 32],
            u * a[1] + v * b[1] + (1 - u - v) * c[1],
          );
      }
  }
  for (const { a, b, count, orientation } of edges.values()) {
    if (count === 1)
      assert.ok(
        (a[0] === b[0] && (a[0] === ox || a[0] === ox + 128)) ||
          (a[2] === b[2] && (a[2] === oz || a[2] === oz + 128)),
        `interior hole at ${a} -> ${b}`,
      );
    else {
      assert.equal(count, 2, "non-manifold edge");
      assert.equal(
        orientation,
        0,
        `inconsistent winding ${key(m.coord.x, m.coord.z)} ${a} -> ${b}`,
      );
    }
  }
  assert.ok(
    top.every(Number.isFinite),
    `terrain hole in chunk ${key(m.coord.x, m.coord.z)}`,
  );
  assert.ok(top.every((y) => y > minHeight && y < 96));
  return sides.map((s) => sha(JSON.stringify([...s].sort())));
}

const aerodrome = process.argv.includes("--aerodrome");
const harbor = process.argv.includes("--harbor");
if (aerodrome && harbor) throw new Error("Select one world profile");
const catalog = aerodrome || harbor
  ? JSON.parse(readFileSync("frontend/public/catalog/catalog.json", "utf8"))
      .assets
  : [];
const output = harbor ? "artifacts/sf09" : aerodrome ? "artifacts/sf04" : "artifacts/sf02r";
const specFor = (seed: number) => harbor ? harborWorldSpec(seed, catalog) :
  aerodrome ? aerodromeWorldSpec(seed, catalog) : defaultWorldSpec(seed);
for (const seed of [0, 48291]) {
  const started = performance.now();
  const world = createWorld(specFor(seed)),
    coords = chunkCoordinates(world);
  const records: Record<
    string,
    {
      geometry: string;
      placements: string;
      triangles: number;
      boundary: string[];
    }
  > = {};
  const ids = new Set<string>();
  let triangles = 0;
  for (const [i, c] of coords.entries()) {
    const m = meshChunk(world, c),
      placements = chunkPlacements(world, c);
    const geometry = sha(
      `${sha(m.positions)}:${sha(m.normals)}:${sha(m.colors)}`,
    );
    const boundary = inspect(m, harbor ? -32 : 0);
    records[key(c.x, c.z)] = {
      geometry,
      placements: sha(JSON.stringify(placements)),
      triangles: m.positions.length / 9,
      boundary,
    };
    triangles += m.positions.length / 9;
    for (const p of placements) {
      assert.ok(!ids.has(p.id));
      ids.add(p.id);
    }
    if (i % 32 === 31) console.log(`Verified ${i + 1}/256 chunks`);
  }
  let seams = 0;
  for (const c of coords) {
    const a = records[key(c.x, c.z)],
      east = records[key(c.x + 1, c.z)],
      south = records[key(c.x, c.z + 1)];
    if (east) {
      assert.equal(a.boundary[1], east.boundary[0], `x seam ${key(c.x, c.z)}`);
      seams++;
    }
    if (south) {
      assert.equal(a.boundary[3], south.boundary[2], `z seam ${key(c.x, c.z)}`);
      seams++;
    }
  }
  // Recreate the world and request chunks in a different, deterministic shuffled order.
  const replay = createWorld(specFor(seed));
  const shuffled = [...coords].sort((a, b) =>
    sha(key(a.x, a.z)).localeCompare(sha(key(b.x, b.z))),
  );
  for (const [i, c] of shuffled.entries()) {
    const m = meshChunk(replay, c),
      previous = records[key(c.x, c.z)];
    assert.equal(
      sha(`${sha(m.positions)}:${sha(m.normals)}:${sha(m.colors)}`),
      previous.geometry,
    );
    assert.equal(
      sha(JSON.stringify(chunkPlacements(replay, c))),
      previous.placements,
    );
    if (i % 64 === 63) console.log(`Replayed ${i + 1}/256 chunks`);
  }
  const report = {
    profile: harbor ? "sf09-harbor-world.v1" :
      aerodrome ? "sf04-aerodrome-world.v1" : "sf02r-connected-world.v2",
    seed,
    extent_m: world.spec.extent_m,
    chunk_size_m: 128,
    cell_size_m: 4,
    chunks: coords.length,
    seams,
    vertical_probes: 256 * 32 * 32,
    triangles,
    placements: ids.size,
    world_sha256: sha(JSON.stringify(world.spec)),
    elapsed_s: (performance.now() - started) / 1000,
    records,
  };
  mkdirSync(output, { recursive: true });
  writeFileSync(
    `${output}/world-verification-${seed}.json`,
    JSON.stringify(report, null, 2) + "\n",
  );
  console.log(JSON.stringify({ ...report, records: undefined }, null, 2));
}
