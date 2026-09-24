import type { AssetRecord, WorldSpec } from "@yulab/contracts";
import { defaultWorldSpec, type Feature, type Vec3 } from "./field.ts";
import { hash } from "./noise.ts";

export const AERODROME_GENERATOR = "aerodrome-world.v1";
export const AERODROME_FIELD = "aerodrome-field.v1";
export const PAD_Y = 24;
export const SURFACE_Y = 24.04;
export type Structure = {
  id: string;
  kind: "pavement" | "marking" | "building" | "fence";
  center: Vec3;
  size: Vec3;
  color: string;
};

/** Rectangular smooth grading envelope: 32 m transition outside a flat inner pad. */
export function gradeWeight(f: Feature, x: number, z: number) {
  const distance = Math.max(
    Math.abs(x - f.center_m[0]) - f.extent_m[0] / 2,
    Math.abs(z - f.center_m[2]) - f.extent_m[2] / 2,
    0,
  );
  const t = Math.min(1, distance / 32);
  return 1 - t * t * (3 - 2 * t);
}

export function aerodromeWorldSpec(
  seed: number,
  catalog: readonly AssetRecord[],
  mode: "fixtures" | "catalog" | "background" = "fixtures",
): WorldSpec {
  const spec = defaultWorldSpec(seed);
  spec.world_id = mode === "fixtures" ? `aerodrome-${seed}` : `aerodrome-${mode}-${seed}`;
  spec.generator_version = AERODROME_GENERATOR;
  spec.field_version = AERODROME_FIELD;
  // The pad and a broad shoulder reserve the site from volumetric landmarks.
  spec.features = spec.features.filter(
    (f) =>
      Math.abs(f.center_m[0] - 64) > 256 + f.extent_m[0] * 0.6 ||
      Math.abs(f.center_m[2]) > 704 + f.extent_m[2] * 0.6,
  );
  spec.features.unshift({
    id: "aerodrome",
    type: "aerodrome",
    center_m: [64, PAD_Y, 0],
    extent_m: [448, 8, 1280],
    seed,
  });
  if (mode === "background") return spec;
  const add = (
    id: string,
    assetId: string,
    x: number,
    z: number,
    yaw = 0,
    operatingState: WorldSpec["instances"][number]["operating_state"] = "off",
  ) => {
    const asset = catalog.find((a) => a.asset_id === assetId);
    if (!asset)
      throw new Error(`${assetId}: required catalog asset is missing`);
    const c = Math.cos(yaw),
      s = Math.sin(yaw);
    spec.instances.push({
      instance_id: `${spec.world_id}-${id}`,
      asset_id: assetId,
      asset_sha256: asset.content_sha256,
      T_world_from_asset: [
        c,
        0,
        s,
        x,
        0,
        1,
        0,
        SURFACE_Y,
        -s,
        0,
        c,
        z,
        0,
        0,
        0,
        1,
      ],
      operating_state: operatingState,
    });
  };
  const jitter = (channel: number) => (hash(0, channel, 0, seed) - 0.5) * 8;
  if (mode === "catalog") {
    const choose = (ids: string[], count: number, channel: number) =>
      [...ids].sort((a, b) => {
        const score = (id: string) => [...id].reduce((n, ch) => n * 31 + ch.charCodeAt(0), 7) >>> 0;
        return hash(score(a), channel, 0, seed) - hash(score(b), channel, 0, seed);
      }).slice(0, count);
    const aircraft = choose(["f16", "rq4", "a10", "f14", "f16xl", "f18", "mq9", "su35"], 4, 211);
    const vehicles = choose(["ground-vehicle", "complex-radar", "simulation-radar", "spaa"], 2, 212);
    aircraft.forEach((id, i) => add(`catalog-air-${i}`, id,
      25 + i * 55 + jitter(220 + i), -88 + jitter(230 + i),
      jitter(240 + i) * 0.014));
    vehicles.forEach((id, i) => add(`catalog-ground-${i}`, id,
      80 + i * 105 + jitter(250 + i), 120 + jitter(260 + i),
      Math.PI / 2 + jitter(270 + i) * 0.02));
    return spec;
  }
  add("clear", "f16", 40 + jitter(101), 70 + jitter(102), jitter(103) * 0.03, "running");
  add("wide", "rq4", 60 + jitter(104), 0 + jitter(105), 0, "idle");
  add("partial", "f16", 180, 50, 0, "idle"); // partial line of sight through the open hangar entrance
  add("hidden", "f16", 210, -40);
  add(
    "service",
    "ground-vehicle",
    110 + jitter(106),
    105 + jitter(107),
    Math.PI / 2,
    "running",
  );
  return spec;
}

export function aerodromeStructures(mode: "fixtures" | "catalog" | "background" = "fixtures"): Structure[] {
  const out: Structure[] = [];
  const box = (
    id: string,
    kind: Structure["kind"],
    center: Vec3,
    size: Vec3,
    color: string,
  ) => out.push({ id, kind, center, size, color });
  const pavement = (
    id: string,
    x: number,
    z: number,
    w: number,
    d: number,
    color = "#626866",
  ) => box(id, "pavement", [x, 24.02, z], [w, 0.04, d], color);
  pavement("runway", -80, 0, 40, 1200, "#4b5354");
  pavement("taxiway", -20, 0, 16, 1000);
  pavement("apron", 110, 20, 240, 240, "#a3a69c");
  for (const z of [-420, 0, 420]) pavement(`connector-${z}`, -50, z, 60, 16);
  pavement("road", 264, 0, 8, 1100, "#74766c");
  pavement("service-road", 200, 105, 132, 8, "#74766c");
  if (mode === "catalog") {
    pavement("catalog-apron-air", 115, -88, 270, 105, "#a3a69c");
    pavement("catalog-apron-ground", 132, 120, 245, 80, "#a3a69c");
    for (let i = 0; i < 4; i++)
      box(`catalog-stand-air-${i}`, "marking", [25 + i * 55, 24.047, -88],
        [0.25, 0.014, 70], "#e4bb51");
    for (let x = -15; x <= 245; x += 25)
      box(`catalog-joint-x-${x}`, "marking", [x, 24.047, -88],
        [0.09, 0.014, 104], "#858b83");
    for (let z = -130; z <= -40; z += 22)
      box(`catalog-joint-z-${z}`, "marking", [115, 24.047, z],
        [268, 0.014, 0.09], "#858b83");
    box("catalog-apron-edge", "marking", [115, 24.048, -138],
      [267, 0.014, 0.28], "#ead8a9");
  }
  for (let z = -560; z <= 560; z += 40)
    box(
      `centerline-${z}`,
      "marking",
      [-80, 24.047, z],
      [0.8, 0.014, 20],
      "#e9e8d7",
    );
  for (const x of [-98, -62])
    box(`edge-${x}`, "marking", [x, 24.047, 0], [0.35, 0.014, 1190], "#e9e8d7");
  for (const z of [-570, 570])
    for (let x = -95; x <= -65; x += 5)
      box(
        `threshold-${x}-${z}`,
        "marking",
        [x, 24.047, z],
        [2, 0.014, 20],
        "#efeddb",
      );
  box("taxi-center", "marking", [-20, 24.047, 0], [0.3, 0.014, 995], "#e4bb51");
  for (const z of [-75, 0, 70])
    box(
      `apron-guide-${z}`,
      "marking",
      [65, 24.047, z],
      [75, 0.014, 0.25],
      "#e4bb51",
    );
  // Actual wall/roof volumes with open fronts, not solid stand-in boxes.
  for (const [id, x, z, closed] of [
    ["open", 180, 50, false],
    ["closed", 210, -40, true],
  ] as const) {
    box(`${id}-back`, "building", [x, 30, z - 19.5], [60, 12, 1], "#9caaab");
    for (const side of [-1, 1])
      box(
        `${id}-side-${side}`,
        "building",
        [x + side * 29.5, 30, z],
        [1, 12, 40],
        "#879798",
      );
    box(`${id}-roof`, "building", [x, 36.5, z], [62, 1, 42], "#667b7c");
    if (closed)
      box(`${id}-door`, "building", [x, 30, z + 19.5], [60, 12, 1], "#849798");
    else {
      box(
        `${id}-door-panel`,
        "building",
        [x - 20, 30, z + 19.5],
        [20, 12, 1],
        "#849798",
      );
      box(`${id}-lintel`, "building", [x, 35, z + 19.5], [60, 2, 1], "#849798");
    }
  }
  box("tower-shaft", "building", [248, 34, 135], [9, 20, 9], "#c3c0ae");
  box("tower-cabin", "building", [248, 45, 135], [15, 4, 15], "#536d75");
  box("tower-roof", "building", [248, 47.5, 135], [17, 1, 17], "#617573");
  for (let z = -624; z <= 624; z += 16)
    for (const x of [-144, 280])
      box(
        `perimeter-${x}-${z}`,
        "fence",
        [x, 25.2, z],
        [0.18, 2.4, 0.18],
        "#8c9184",
      );
  return out;
}

export const aerodromeFixtures = [
  {
    id: "clear",
    name: "Unobstructed F-16",
    position: [38, 30, 102] as Vec3,
    target: [40, 26.5, 70] as Vec3,
  },
  {
    id: "partial",
    name: "Partial hangar occlusion",
    position: [151, 28, 106] as Vec3,
    target: [180, 26.5, 50] as Vec3,
  },
  {
    id: "hidden",
    name: "Closed hangar",
    position: [210, 28, 15] as Vec3,
    target: [210, 26.5, -40] as Vec3,
  },
];
