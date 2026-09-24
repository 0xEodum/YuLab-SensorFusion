import type { AssetRecord, WorldSpec } from "@yulab/contracts";
import { defaultWorldSpec, terrainHeight, type Vec3 } from "./field.ts";
import type { Structure } from "./aerodrome.ts";
import { hash, noise } from "./noise.ts";

export const HARBOR_GENERATOR = "harbor-world.v1";
export const HARBOR_FIELD = "harbor-field.v1";
export const HARBOR_WATER_Y = 6;
export const HARBOR_QUAY_Y = 14;

const clamp = (v: number) => Math.max(0, Math.min(1, v));
const smooth = (v: number) => { const t = clamp(v); return t * t * (3 - 2 * t); };

/** The shore is one continuous world-space curve, shared by terrain and water. */
export function harborShoreX(z: number, seed: number) {
  return 66 + 12 * Math.sin(z / 137 + seed * 0.001) +
    9 * noise(0, 3, z / 228, seed + 901);
}

export function harborHeight(x: number, z: number, seed: number) {
  const shore = harborShoreX(z, seed);
  const seabed = -10 + 1.7 * noise(x / 88, 0, z / 88, seed + 907);
  const native = terrainHeight(x, z, seed);
  const quay = smooth((Math.abs(z) - 350) / 65);
  const land = HARBOR_QUAY_Y * (1 - quay) + native * quay;
  return seabed * (1 - smooth((x - shore + 20) / 52)) +
    land * smooth((x - shore + 20) / 52);
}

export function harborWorldSpec(
  seed: number,
  catalog: readonly AssetRecord[],
  mode: "mixed" | "background" = "mixed",
): WorldSpec {
  const spec = defaultWorldSpec(seed);
  spec.world_id = `harbor-${mode}-${seed}`;
  spec.generator_version = HARBOR_GENERATOR;
  spec.field_version = HARBOR_FIELD;
  spec.features = spec.features.filter((f) =>
    Math.abs(f.center_m[0]) > 420 + f.extent_m[0] * 0.6 ||
    Math.abs(f.center_m[2]) > 460 + f.extent_m[2] * 0.6,
  );
  spec.features.unshift({
    id: "harbor",
    type: "harbor",
    center_m: [64, HARBOR_QUAY_Y, 0],
    extent_m: [512, 8, 768],
    seed,
  });
  if (mode === "background") return spec;
  const add = (assetId: string, slot: number, z: number) => {
    const asset = catalog.find((record) => record.asset_id === assetId);
    if (!asset) throw new Error(`${assetId}: required harbor asset is missing`);
    const x = -147 + (hash(slot, 7, 0, seed) - 0.5) * 12;
    const dz = (hash(slot, 8, 0, seed) - 0.5) * 12;
    const yaw = Math.PI / 2 + (hash(slot, 9, 0, seed) - 0.5) * 0.08;
    const c = Math.cos(yaw), s = Math.sin(yaw);
    spec.instances.push({
      instance_id: `${spec.world_id}-${assetId}-${slot}`,
      asset_id: assetId,
      asset_sha256: asset.content_sha256,
      T_world_from_asset: [c, 0, s, x, 0, 1, 0, HARBOR_WATER_Y,
        -s, 0, c, z + dz, 0, 0, 0, 1],
      operating_state: "idle",
    });
  };
  add("cruiser", 1, -65);
  add("destroyer", 2, 65);
  return spec;
}

export function harborStructures(): Structure[] {
  const out: Structure[] = [];
  const box = (id: string, kind: Structure["kind"], center: Vec3,
    size: Vec3, color: string) => out.push({ id, kind, center, size, color });
  box("quay-wall", "building", [84, 3, 0], [9, 22, 710], "#68757a");
  box("quay-cap", "pavement", [133, 14.04, 0], [106, 0.08, 710], "#a9aa9c");
  box("quay-road", "pavement", [190, 14.06, 0], [16, 0.04, 685], "#565f62");
  for (const z of [-330, -110, 110, 330])
    box(`quay-lane-${z}`, "marking", [190, 14.088, z], [0.22, 0.015, 72], "#e5d7ad");
  for (const [index, z] of [-160, 0, 160].entries()) {
    box(`pier-${index}`, "pavement", [-35, 12.8, z], [238, 0.7, 14], "#aab2ab");
    box(`pier-edge-${index}`, "marking", [-35, 13.17, z - 6.6], [238, 0.05, 0.32], "#dfd8ac");
    for (const x of [-145, -85, -25, 35]) {
      box(`pier-pile-${index}-${x}-a`, "building", [x, 1.8, z - 5], [2.5, 22, 2.5], "#636d6c");
      box(`pier-pile-${index}-${x}-b`, "building", [x, 1.8, z + 5], [2.5, 22, 2.5], "#636d6c");
      box(`pier-bollard-${index}-${x}`, "fence", [x, 13.6, z + 5], [0.9, 0.9, 0.9], "#29383b");
    }
  }
  for (const [side, z] of [[-1, -260], [1, 260]] as const) {
    box(`breakwater-${side}`, "building", [-280, 2, z], [320, 19, 15], "#647476");
    box(`breakwater-cap-${side}`, "pavement", [-280, 11.6, z], [320, 0.4, 16], "#b3b9af");
    box(`beacon-base-${side}`, "building", [-415, 14.5, z], [5, 6, 5], "#f0e2bd");
    box(`beacon-head-${side}`, "building", [-415, 19, z], [7, 3, 7],
      side < 0 ? "#ce6254" : "#6eaa9d");
  }
  const containerColors = ["#ba6951", "#718b88", "#d5a75f", "#596c77", "#8d806a"];
  for (let row = 0; row < 2; row++)
    for (let col = 0; col < 4; col++) {
      const x = 130 + row * 15, z = -58 + col * 29;
      box(`container-central-${row}-${col}`, "building", [x, 15.55, z],
        [12, 3, 24], containerColors[(row * 2 + col) % containerColors.length]);
      if (col % 2 === 0)
        box(`container-central-upper-${row}-${col}`, "building", [x, 18.6, z],
          [12, 3, 24], containerColors[(row * 2 + col + 2) % containerColors.length]);
    }
  for (let row = 0; row < 3; row++)
    for (let col = 0; col < 5; col++) {
      const x = 130 + row * 15, z = -295 + col * 29;
      box(`container-south-${row}-${col}`, "building", [x, 15.5, z], [12, 3, 24],
        containerColors[(row + col) % containerColors.length]);
      if ((row + col) % 3 !== 0)
        box(`container-south-upper-${row}-${col}`, "building", [x, 18.55, z],
          [12, 3, 24], containerColors[(row + col + 2) % containerColors.length]);
    }
  for (const z of [185, 275]) {
    box(`warehouse-${z}`, "building", [239, 22, z], [62, 16, 64], "#8f9b99");
    box(`warehouse-roof-${z}`, "building", [239, 30.8, z], [66, 2, 68], "#596d72");
    for (const x of [222, 240, 258])
      box(`warehouse-door-${z}-${x}`, "building", [x, 18, z - 32.2],
        [12, 8, 0.5], "#52656a");
  }
  box("harbor-office", "building", [225, 20, 15], [42, 12, 42], "#8c9b9a");
  box("harbor-office-roof", "building", [225, 26.8, 15], [46, 1.5, 46], "#4b656e");
  for (const z of [-1, 12, 25])
    box(`harbor-office-window-${z}`, "building", [203.5, 21, z],
      [0.5, 3.4, 7], "#344d5b");
  for (const z of [-225, -70, 80, 225]) {
    box(`gantry-leg-a-${z}`, "building", [95, 26, z - 10], [3, 24, 3], "#d59c5c");
    box(`gantry-leg-b-${z}`, "building", [95, 26, z + 10], [3, 24, 3], "#d59c5c");
    box(`gantry-beam-${z}`, "building", [95, 39, z], [5, 3, 27], "#c68f55");
    box(`gantry-boom-${z}`, "building", [26, 40, z], [140, 2, 3], "#d6a05c");
    box(`gantry-cable-${z}`, "fence", [-27, 30, z], [0.35, 20, 0.35], "#424b4b");
  }
  return out;
}
