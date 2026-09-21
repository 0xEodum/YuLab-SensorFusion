import {
  assertChunk,
  biomeWeight,
  type World,
  type ChunkCoord,
  type Vec3,
} from "./field.ts";
import { hash } from "./noise.ts";
import { gradeWeight } from "./aerodrome.ts";

export type Placement = {
  id: string;
  kind: "rock" | "tree";
  position: Vec3;
  scale: number;
  yaw: number;
};
/** One independently seeded candidate per 16 m global cell; half-open ownership. */
export function chunkPlacements(w: World, c: ChunkCoord): Placement[] {
  assertChunk(w, c);
  const result: Placement[] = [];
  for (let gx = c.x * 8; gx < (c.x + 1) * 8; gx++)
    for (let gz = c.z * 8; gz < (c.z + 1) * 8; gz++) {
      const r = (channel: number) => hash(gx, channel, gz, w.spec.seed);
      if (r(21) > 0.56) continue;
      const x = (gx + 0.12 + 0.76 * r(22)) * 16,
        z = (gz + 0.12 + 0.76 * r(23)) * 16;
      if (
        w.spec.features.some(
          (f) => f.type === "aerodrome" && gradeWeight(f, x, z) > 0,
        )
      )
        continue;
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
      const up = w.normal(x, y, z)[1];
      if (up < 0.72) continue;
      const wooded = biomeWeight(x, z, w.spec.seed) > 0.3;
      const kind =
        r(26) < 0.68 && up > 0.8 && y < 52 && wooded ? "tree" : "rock";
      result.push({
        id: `${w.spec.world_id}-${kind}-${gx}-${gz}`,
        kind,
        position: [x, y, z],
        scale: kind === "tree" ? 3.5 + r(24) * 4.8 : 0.8 + r(24) * 2.2,
        yaw: r(25) * Math.PI * 2,
      });
    }
  return result;
}
