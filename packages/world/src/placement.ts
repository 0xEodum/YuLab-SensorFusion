import {
  assertChunk,
  type World,
  type ChunkCoord,
  type Vec3,
} from './field.ts';
import { hash } from './noise.ts';

export type Placement = {
  id: string;
  kind: 'rock';
  position: Vec3;
  scale: number;
  yaw: number;
};
/** One independently seeded candidate per 32 m global cell; half-open ownership. */
export function chunkPlacements(w: World, c: ChunkCoord): Placement[] {
  assertChunk(w, c);
  const result: Placement[] = [];
  for (let gx = c.x * 4; gx < (c.x + 1) * 4; gx++)
    for (let gz = c.z * 4; gz < (c.z + 1) * 4; gz++) {
      const r = (channel: number) => hash(gx, channel, gz, w.spec.seed);
      if (r(21) > 0.38) continue;
      const x = (gx + 0.15 + 0.7 * r(22)) * 32,
        z = (gz + 0.15 + 0.7 * r(23)) * 32;
      // Find the top surface of the same field. Never use the load order's mesh state.
      let y = 96;
      for (; y > -32; y -= 1) if (w.density(x, y, z) >= 0) break;
      let lo = y,
        hi = y + 1;
      for (let i = 0; i < 20; i++) {
        const mid = (lo + hi) / 2;
        if (w.density(x, mid, z) >= 0) lo = mid;
        else hi = mid;
      }
      y = (lo + hi) / 2;
      if (w.normal(x, y, z)[1] < 0.85) continue;
      result.push({
        id: `${w.spec.world_id}-rock-${gx}-${gz}`,
        kind: 'rock',
        position: [x, y, z],
        scale: 1 + r(24) * 2,
        yaw: r(25) * Math.PI * 2,
      });
    }
  return result;
}
