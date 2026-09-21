export function hash(x: number, y: number, z: number, seed: number) {
  let n = Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(z, 1442695041) + seed;
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
}
export function noise(x: number, y: number, z: number, seed: number) {
  const ix = Math.floor(x), iy = Math.floor(y), iz = Math.floor(z);
  let fx = x - ix, fy = y - iy, fz = z - iz;
  fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy); fz = fz * fz * (3 - 2 * fz);
  const mix = (a: number, b: number, t: number) => a + (b - a) * t;
  return mix(mix(mix(hash(ix, iy, iz, seed), hash(ix + 1, iy, iz, seed), fx), mix(hash(ix, iy + 1, iz, seed), hash(ix + 1, iy + 1, iz, seed), fx), fy), mix(mix(hash(ix, iy, iz + 1, seed), hash(ix + 1, iy, iz + 1, seed), fx), mix(hash(ix, iy + 1, iz + 1, seed), hash(ix + 1, iy + 1, iz + 1, seed), fx), fy), fz) * 2 - 1;
}
