import {
  assertChunk,
  type World,
  type ChunkCoord,
  type Vec3,
} from './field.ts';

export type ChunkMesh = {
  coord: ChunkCoord;
  cellSize: number;
  positions: Float32Array;
  normals: Float32Array;
  colors: Float32Array;
};
const corners: Vec3[] = [
  [0, 0, 0],
  [1, 0, 0],
  [1, 1, 0],
  [0, 1, 0],
  [0, 0, 1],
  [1, 0, 1],
  [1, 1, 1],
  [0, 1, 1],
];
// Consistent Freudenthal split: every cube uses the same 0 -> 6 body diagonal.
// Shared faces consequently use identical diagonals on both sides of a chunk.
const tetrahedra = [
  [0, 1, 2, 6],
  [0, 2, 3, 6],
  [0, 3, 7, 6],
  [0, 7, 4, 6],
  [0, 4, 5, 6],
  [0, 5, 1, 6],
];

/** Pure meshing on a global integer lattice. No Three.js, renderer, RNG or resident neighbors. */
export function meshChunk(
  world: World,
  coord: ChunkCoord,
  cellSize = 4,
): ChunkMesh {
  assertChunk(world, coord);
  if (cellSize !== 2 && cellSize !== 4)
    throw new Error('cell size must be 2 or 4 metres');
  const n = 128 / cellSize,
    side = n + 1,
    ox = coord.x * 128,
    oz = coord.z * 128,
    oy = -32;
  const field = new Float64Array(side ** 3);
  const index = (x: number, y: number, z: number) => x + side * (y + side * z);
  for (let z = 0; z <= n; z++)
    for (let y = 0; y <= n; y++)
      for (let x = 0; x <= n; x++) {
        const d = world.density(
          ox + x * cellSize,
          oy + y * cellSize,
          oz + z * cellSize,
        );
        // A global 1 cm isovalue tie band avoids sub-ULP sliver triangles when
        // metre coordinates are stored as Float32. Identical on every shared node.
        field[index(x, y, z)] = Math.abs(d) < 0.01 ? 0.01 : d;
      }
  const positions: number[] = [],
    normals: number[] = [],
    colors: number[] = [];
  type Vertex = { p: Vec3; n: Vec3; c: Vec3 };
  const edgeCache = new Map<string, Vertex>();
  const tri = (a: Vertex, b: Vertex, c: Vertex, outward: number[]) => {
    const u = b.p.map((v, i) => v - a.p[i]),
      v = c.p.map((v, i) => v - a.p[i]);
    const cross = [
      u[1] * v[2] - u[2] * v[1],
      u[2] * v[0] - u[0] * v[2],
      u[0] * v[1] - u[1] * v[0],
    ];
    if (Math.hypot(...cross) < 1e-9) return;
    // Orient against the sampled tetrahedron's solid/air separation. Smoothed
    // field gradients can point across a sharp CSG crease and invert a face.
    if (cross.reduce((s, v, i) => s + v * outward[i], 0) < 0) [b, c] = [c, b];
    for (const vert of [a, b, c]) {
      positions.push(...vert.p);
      normals.push(...vert.n);
      colors.push(...vert.c);
    }
  };
  for (let z = 0; z < n; z++)
    for (let y = 0; y < n; y++)
      for (let x = 0; x < n; x++) {
        const ids = corners.map((c) => index(x + c[0], y + c[1], z + c[2]));
        const ds = ids.map((i) => field[i]);
        if (ds.every((d) => d >= 0) || ds.every((d) => d < 0)) continue;
        const ps = corners.map(
          (c) =>
            [
              ox + (x + c[0]) * cellSize,
              oy + (y + c[1]) * cellSize,
              oz + (z + c[2]) * cellSize,
            ] as Vec3,
        );
        const edge = (a: number, b: number): Vertex => {
          // Canonical endpoint order also fixes rounding at faces owned by different chunks.
          if (ids[a] > ids[b]) [a, b] = [b, a];
          const key = `${ids[a]},${ids[b]}`;
          const cached = edgeCache.get(key);
          if (cached) return cached;
          const t = ds[a] / (ds[a] - ds[b]);
          const p = ps[a].map((v, i) =>
            Math.fround(v + (ps[b][i] - v) * t),
          ) as Vec3;
          // Evaluate attributes at the stored vertex, not at chunk-local/face averages.
          const normal = world.normal(...p),
            c = world.color(...p, normal[1]);
          const vertex = { p, n: normal, c };
          edgeCache.set(key, vertex);
          return vertex;
        };
        for (const tet of tetrahedra) {
          const inside = tet.filter((i) => ds[i] >= 0),
            outside = tet.filter((i) => ds[i] < 0);
          if (!inside.length || !outside.length) continue;
          const outward = ps[outside[0]].map((v, i) => v - ps[inside[0]][i]);
          if (inside.length === 1)
            tri(
              edge(inside[0], outside[0]),
              edge(inside[0], outside[1]),
              edge(inside[0], outside[2]),
              outward,
            );
          else if (inside.length === 3)
            tri(
              edge(outside[0], inside[0]),
              edge(outside[0], inside[1]),
              edge(outside[0], inside[2]),
              outward,
            );
          else if (inside.length === 2) {
            const a = edge(inside[0], outside[0]),
              b = edge(inside[0], outside[1]),
              c = edge(inside[1], outside[0]),
              d = edge(inside[1], outside[1]);
            tri(a, b, c, outward);
            tri(b, d, c, outward);
          }
        }
      }
  return {
    coord: { ...coord },
    cellSize,
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    colors: new Float32Array(colors),
  };
}
