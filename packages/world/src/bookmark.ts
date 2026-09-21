import type { WorldSpec } from "@yulab/contracts";
import type { Vec3 } from "./field.ts";

export type RigBookmark = {
  version: "rig-bookmark.v1";
  name: string;
  world: WorldSpec;
  position: Vec3;
  quaternion: [number, number, number, number];
  target: Vec3;
  navigation: "orbit" | "flight";
  pitch: 2 | 4;
};
/** Local inspection-rig bookmark, not a calibrated RigSpec or sensor output. */
export function validateBookmark(
  value: unknown,
  world: WorldSpec,
): RigBookmark {
  const b = value as RigBookmark;
  const vector = (a: unknown, n: number) =>
    Array.isArray(a) &&
    a.length === n &&
    Array.from(a).every((v) => typeof v === "number" && Number.isFinite(v));
  if (
    !b ||
    b.version !== "rig-bookmark.v1" ||
    typeof b.name !== "string" ||
    !b.name.trim() ||
    b.name.length > 64 ||
    JSON.stringify(b.world) !== JSON.stringify(world) ||
    !vector(b.position, 3) ||
    !vector(b.target, 3) ||
    !vector(b.quaternion, 4) ||
    Math.abs(Math.hypot(...b.quaternion) - 1) > 1e-6 ||
    !["orbit", "flight"].includes(b.navigation) ||
    ![2, 4].includes(b.pitch)
  )
    throw new Error("Invalid or incompatible rig bookmark");
  for (const axis of [0, 2] as const)
    if (
      b.position[axis] < world.origin_m[axis] ||
      b.position[axis] >= world.origin_m[axis] + world.extent_m[axis] ||
      b.target[axis] < world.origin_m[axis] ||
      b.target[axis] >= world.origin_m[axis] + world.extent_m[axis]
    )
      throw new Error("Rig bookmark outside finite world");
  return structuredClone(b);
}
