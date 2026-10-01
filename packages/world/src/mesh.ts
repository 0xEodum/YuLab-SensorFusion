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
    for (let x = 0; x <= n; x++) {
      const column = world.densityColumn(ox + x * cellSize, oz + z * cellSize);
      for (let y = 0; y <= n; y++) {
        const d = column(oy + y * cellSize);
        // A global 1 cm isovalue tie band avoids sub-ULP sliver triangles when
        // metre coordinates are stored as Float32. Identical on every shared node.
        field[index(x, y, z)] = Math.abs(d) < 0.01 ? 0.01 : d;
      }
    }
  const positions: number[] = [],
    normals: number[] = [],
    colors: number[] = [];
  type Vertex = { p: Vec3; n: Vec3; c: Vec3 };
  // Lattice node pairs fit exactly in a double: side**3 squared < 2**53.
  const nodes = side ** 3;
  const edgeCache = new Map<number, Vertex>();
  const push = (vert: Vertex) => {
    positions.push(vert.p[0], vert.p[1], vert.p[2]);
    normals.push(vert.n[0], vert.n[1], vert.n[2]);
    colors.push(vert.c[0], vert.c[1], vert.c[2]);
  };
  const tri = (a: Vertex, b: Vertex, c: Vertex, outward: Vec3) => {
    const u0 = b.p[0] - a.p[0], u1 = b.p[1] - a.p[1], u2 = b.p[2] - a.p[2];
    const v0 = c.p[0] - a.p[0], v1 = c.p[1] - a.p[1], v2 = c.p[2] - a.p[2];
    const c0 = u1 * v2 - u2 * v1,
      c1 = u2 * v0 - u0 * v2,
      c2 = u0 * v1 - u1 * v0;
    if (Math.hypot(c0, c1, c2) < 1e-9) return;
    // Orient against the sampled tetrahedron's solid/air separation. Smoothed
    // field gradients can point across a sharp CSG crease and invert a face.
    push(a);
    if (0 + c0 * outward[0] + c1 * outward[1] + c2 * outward[2] < 0) {
      push(c);
      push(b);
    } else {
      push(b);
      push(c);
    }
  };
  const ids = new Array<number>(8),
    ds = new Array<number>(8),
    ps = corners.map(() => [0, 0, 0] as Vec3);
  const inside: number[] = [],
    outside: number[] = [];
  const edge = (a: number, b: number): Vertex => {
    // Canonical endpoint order also fixes rounding at faces owned by different chunks.
    if (ids[a] > ids[b]) [a, b] = [b, a];
    const key = ids[a] * nodes + ids[b];
    const cached = edgeCache.get(key);
    if (cached) return cached;
    const t = ds[a] / (ds[a] - ds[b]);
    const pa = ps[a],
      pb = ps[b];
    const p: Vec3 = [
      Math.fround(pa[0] + (pb[0] - pa[0]) * t),
      Math.fround(pa[1] + (pb[1] - pa[1]) * t),
      Math.fround(pa[2] + (pb[2] - pa[2]) * t),
    ];
    // Evaluate attributes at the stored vertex, not at chunk-local/face averages.
    const normal = world.normal(p[0], p[1], p[2]),
      c = world.color(p[0], p[1], p[2], normal[1]);
    const vertex = { p, n: normal, c };
    edgeCache.set(key, vertex);
    return vertex;
  };
  for (let z = 0; z < n; z++)
    for (let y = 0; y < n; y++)
      for (let x = 0; x < n; x++) {
        let solid = 0;
        for (let k = 0; k < 8; k++) {
          const c = corners[k];
          ids[k] = index(x + c[0], y + c[1], z + c[2]);
          ds[k] = field[ids[k]];
          if (ds[k] >= 0) solid++;
        }
        if (solid === 0 || solid === 8) continue;
        for (let k = 0; k < 8; k++) {
          const c = corners[k];
          ps[k][0] = ox + (x + c[0]) * cellSize;
          ps[k][1] = oy + (y + c[1]) * cellSize;
          ps[k][2] = oz + (z + c[2]) * cellSize;
        }
        for (const tet of tetrahedra) {
          inside.length = 0;
          outside.length = 0;
          for (const i of tet) (ds[i] >= 0 ? inside : outside).push(i);
          if (!inside.length || !outside.length) continue;
          const pi = ps[inside[0]],
            po = ps[outside[0]];
          const outward: Vec3 = [po[0] - pi[0], po[1] - pi[1], po[2] - pi[2]];
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
          else {
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
