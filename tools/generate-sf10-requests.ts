/** Deterministic grouped SF-10 pilot requests. No dataset truth enters a request. */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import * as THREE from "three";
import type { AssetRecord, CaptureRequest } from "../packages/contracts/src/generated.ts";
import { validatePayload } from "../packages/contracts/src/validate.ts";
import { aerodromeWorldSpec, harborWorldSpec } from "../packages/world/src/index.ts";
import { cameraPoseToRig } from "../packages/sensors/src/index.ts";
import { environmentPreset, type WeatherPreset } from "../packages/sensors/src/weather.ts";

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(",")}}`;
  return JSON.stringify(value);
}
const digest = (value: unknown) => createHash("sha256").update(canonical(value)).digest("hex");
const argument = (name: string, fallback: number) => {
  const index = process.argv.indexOf(name);
  return index < 0 ? fallback : Number(process.argv[index + 1]);
};
const count = argument("--count", 300), width = argument("--width", 320),
  height = argument("--height", 192), rows = argument("--rows", 32),
  columns = argument("--columns", 256);
const outputIndex = process.argv.indexOf("--output");
const output = outputIndex < 0 ? undefined : process.argv[outputIndex + 1];
const prefixIndex = process.argv.indexOf("--id-prefix");
const idPrefix = prefixIndex < 0 ? "sf10" : process.argv[prefixIndex + 1];
if (!output || output.startsWith("--") || !Number.isInteger(count) || count < 1 || count > 300 ||
    ![width, height, rows, columns].every((n) => Number.isInteger(n) && n > 0) ||
    !/^[a-z][a-z0-9_-]{1,30}$/.test(idPrefix))
  throw new Error("Use --output FILE [--count 1..300] [--width N --height N --rows N --columns N]");
const records = JSON.parse(readFileSync("frontend/public/catalog/catalog.json", "utf8")).assets as AssetRecord[];
const presets: [WeatherPreset, number, number][] = [
  ["clear-day", 0, 12], ["clear-day", 0, 8], ["night", 1, 0],
  ["fog", 0.75, 12], ["fog", 1, 8], ["rain", 0.7, 13],
  ["snow", 0.8, 10], ["hot-background", 0.9, 15],
  ["clear-day", 0, 17], ["night", 1, 21],
];
const layouts = [
  { site: "airfield", seed: 0, split: "train" },
  { site: "airfield", seed: 48291, split: "train" },
  { site: "harbor", seed: 7, split: "train" },
  { site: "harbor", seed: 90210, split: "train" },
  { site: "airfield", seed: 2718, split: "validation" },
  { site: "harbor", seed: 31415, split: "test" },
] as const;
const requests: { group_id: string; split: string; request: CaptureRequest }[] = [];
for (const [layoutIndex, layout] of layouts.entries()) {
  const world = layout.site === "airfield"
    ? aerodromeWorldSpec(layout.seed, records, "catalog")
    : harborWorldSpec(layout.seed, records);
  for (let view = 0; view < 5; view++) for (let condition = 0; condition < 10; condition++) {
    const n = layoutIndex * 50 + view * 10 + condition;
    if (n >= count) continue;
    const viewpoints = layout.site === "airfield" ? [
      [[70, 34, 10], [83, 25, -85]],
      [[130, 35, 0], [135, 25, -90]],
      [[80, 32, 180], [78, 25, 116]],
      [[190, 32, 180], [181, 25, 116]],
      [[30, 32, -15], [23, 25, -90]],
    ] : [
      [[0, 36, -65], [-147, 6, -65]],
      [[0, 36, 65], [-147, 6, 65]],
      [[-60, 28, 160], [-147, 6, 65]],
      [[250, 28, -205], [190, 14, -205]],
      [[250, 28, 120], [190, 14, 120]],
    ];
    const [position, target] = viewpoints[view];
    const base = new THREE.Vector3(...position);
    const center = new THREE.Vector3(...target);
    const camera = new THREE.PerspectiveCamera();
    camera.position.copy(base);
    camera.lookAt(center);
    const rig = cameraPoseToRig({ rigId: `rig-${n}`, position: base.toArray(),
      quaternion: camera.quaternion.toArray(), width, height, verticalFovRadians: Math.PI / 4 });
    const lidar = rig.sensors.find((sensor) => sensor.modality === "lidar")!;
    lidar.lidar!.rows = rows;
    lidar.lidar!.columns = columns;
    const [preset, severity, hour] = presets[condition];
    const environment = environmentPreset(preset, severity, hour, 0);
    const captureId = `${idPrefix}-${String(n).padStart(4, "0")}`;
    const request: CaptureRequest = { schema_version: "lab.v1", kind: "CaptureRequest",
      world, rig, environment,
      plan: { schema_version: "lab.v1", kind: "CapturePlan", capture_id: captureId,
        sequence_id: `seq-${layout.site}-${layout.seed}-${view}`,
        world_sha256: digest(world), rig_sha256: digest(rig),
        environment_sha256: digest(environment), simulation_time_s: 0,
        geometry_policy: "fixed-sensor-geometry", quality_version: "capture-quality.v1",
        seed_channels: { world: layout.seed, rgb: n + 1, ir: n + 2,
          lidar: n + 3, weather: n + 4 }, modalities: ["rgb", "ir", "lidar"] },
    };
    validatePayload("CaptureRequest", request);
    requests.push({ group_id: `${layout.site}-${layout.seed}`, split: layout.split, request });
  }
}
writeFileSync(output, JSON.stringify({ version: "sf10-requests.v1", requests }, null, 2) + "\n");
process.stdout.write(`${requests.length} grouped capture requests written to ${output}\n`);
