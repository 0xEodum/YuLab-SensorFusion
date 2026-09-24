import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type {
  AssetRecord,
  EnvironmentSpec,
  WorldSpec,
} from "../../packages/contracts/src/generated.ts";
import {
  LWIR_RESPONSE_VERSION,
  THERMAL_MODEL_VERSION,
  THERMAL_STATE_VERSION,
  advanceThermalState,
  bandRadiance,
  decodeThermalState,
  encodeThermalState,
  equilibriumTemperature,
  initializeThermalState,
  radianceRaster,
  stepSurfaceTemperature,
  surfaceRadiance,
  thermalPreviewRgba,
} from "../../packages/sensors/src/thermal.ts";

const catalog = JSON.parse(
  readFileSync(
    new URL("../../frontend/public/catalog/catalog.json", import.meta.url),
    "utf8",
  ),
) as { assets: AssetRecord[] };

const environment = (overrides: Partial<EnvironmentSpec> = {}): EnvironmentSpec => ({
  schema_version: "lab.v1",
  kind: "EnvironmentSpec",
  environment_id: "thermal-fixture",
  simulation_time_s: 0,
  solar_time_hour: 0,
  latitude_rad: 0,
  sun_direction_world: [0, 0, 0],
  ambient_temperature_k: 293.15,
  fog_extinction_per_m: 0,
  rain_mm_per_h: 0,
  snow_mm_per_h: 0,
  wind_m_per_s: [0, 0, 0],
  wetness: 0,
  parameter_set_version: "thermal-clear.v1",
  thermal_history: "equilibrated",
  thermal_state: null,
  ...overrides,
});

const world = (operating_state: "off" | "idle" | "running"): WorldSpec => ({
  schema_version: "lab.v1",
  kind: "WorldSpec",
  world_id: `thermal-${operating_state}`,
  seed: 0,
  units: {
    length: "m",
    temperature: "K",
    angle: "rad",
    time: "s",
    world_frame: "east-up-south",
    matrix_layout: "row-major",
  },
  extent_m: [2048, 128, 2048],
  origin_m: [-1024, 0, -1024],
  chunk_size_m: 128,
  generator_version: "aerodrome-world.v1",
  field_version: "aerodrome-field.v1",
  features: [],
  instances: [{
    instance_id: "thermal-aircraft",
    asset_id: "f16",
    asset_sha256: catalog.assets.find((asset) => asset.asset_id === "f16")!.content_sha256,
    T_world_from_asset: [
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, 0, 0, 1,
    ],
    operating_state,
  }],
});

test("catalog surfaces carry implemented thermal metadata and powered exterior regions", () => {
  assert.equal(THERMAL_MODEL_VERSION, "thermal-surface.v1");
  assert.equal(THERMAL_STATE_VERSION, "thermal-state.v1");
  assert.equal(LWIR_RESPONSE_VERSION, "lwir-8-14um.v1");
  for (const asset of catalog.assets) {
    assert.equal(asset.thermal_model_version, THERMAL_MODEL_VERSION);
    assert.ok(asset.materials.every((material) => material.thermal_capacity_j_per_k > 10_000));
    assert.ok(asset.materials.every((material) => material.area_m2 > 0));
    assert.ok(asset.heat_sources.some((source) => source.power_w > 0));
    for (const source of asset.heat_sources) {
      const part = asset.parts.find((candidate) => candidate.id === source.part_id);
      assert.ok(part);
      assert.match(part!.semantic, /engine|exhaust|radiator/);
    }
  }
});

test("every imported asset has an operating-state thermal fixture", () => {
  for (const asset of catalog.assets) {
    const temperatures = (["off", "idle", "running"] as const).map((mode) => {
      const spec = world(mode);
      spec.instances[0].asset_id = asset.asset_id;
      spec.instances[0].asset_sha256 = asset.content_sha256;
      const nodes = initializeThermalState(spec, catalog.assets, environment()).nodes;
      assert.ok(nodes.length >= 2, asset.asset_id);
      assert.ok(nodes.every((node) => Number.isFinite(node.temperature_k)), asset.asset_id);
      return nodes.filter((node) => /engine|exhaust|radiator/.test(node.region_id))
        .map((node) => node.temperature_k);
    });
    assert.ok(temperatures[0].length > 0, asset.asset_id);
    assert.ok(temperatures[0].every((value, i) =>
      value < temperatures[1][i] && temperatures[1][i] < temperatures[2][i]),
    `${asset.asset_id}: powered surfaces must warm monotonically`);
  }
});

test("simple surface equilibrium and fixed steps have the correct energy direction", () => {
  const node = {
    emissivity: 0.9,
    solar_absorption: 0,
    thermal_capacity_j_per_k: 80_000,
    area_m2: 2,
    convection_w_per_m2_k: 12,
    source_power_w: 4_000,
    solar_irradiance_w_per_m2: 0,
    air_temperature_k: 293.15,
    environment_temperature_k: 293.15,
  };
  const equilibrium = equilibriumTemperature(node);
  assert.ok(equilibrium > node.air_temperature_k + 50);
  const warmed = stepSurfaceTemperature(node.air_temperature_k, node, 1);
  assert.ok(warmed > node.air_temperature_k);
  const cooled = stepSurfaceTemperature(equilibrium + 20, { ...node, source_power_w: 0 }, 1);
  assert.ok(cooled < equilibrium + 20);
  let coarse = node.air_temperature_k;
  let fine = node.air_temperature_k;
  for (let i = 0; i < 600; i++) coarse = stepSurfaceTemperature(coarse, node, 1);
  for (let i = 0; i < 2_400; i++) fine = stepSurfaceTemperature(fine, node, 0.25);
  assert.ok(Math.abs(coarse - fine) < 0.05);
  assert.ok(coarse < equilibrium);
});

test("off, idle and running equipment produce ordered engine and exhaust temperatures", () => {
  const states = (["off", "idle", "running"] as const).map((mode) =>
    initializeThermalState(world(mode), catalog.assets, environment()),
  );
  const temperature = (index: number, region: string) =>
    states[index].nodes.find((node) => node.region_id === region)!.temperature_k;
  assert.ok(temperature(0, "body-surface") <= temperature(0, "engine-surface"));
  assert.ok(temperature(0, "engine-surface") < temperature(1, "engine-surface"));
  assert.ok(temperature(1, "engine-surface") < temperature(2, "engine-surface"));
  assert.ok(temperature(2, "exhaust-surface") > temperature(2, "body-surface") + 20);
});

test("engine-off cooldown is identical across a thermal-state save and reload", () => {
  const running = initializeThermalState(world("running"), catalog.assets, environment());
  const shutdownWorld = world("off");
  const target = environment({ simulation_time_s: 300, thermal_history: "continued" });
  const uninterrupted = advanceThermalState(running, shutdownWorld, catalog.assets, target);
  const restored = advanceThermalState(
    decodeThermalState(encodeThermalState(running)),
    shutdownWorld,
    catalog.assets,
    target,
  );
  assert.deepEqual(restored, uninterrupted);
  for (let i = 0; i < restored.nodes.length; i++)
    assert.ok(restored.nodes[i].temperature_k <= running.nodes[i].temperature_k);
  assert.throws(
    () => decodeThermalState('{"version":"future"}'),
    /thermal state version/i,
  );
});

test("8..14 um radiance is monotonic, emissivity-aware and loses contrast at crossover", () => {
  const cold = bandRadiance(280);
  const warm = bandRadiance(320);
  assert.ok(warm > cold && cold > 0);
  const reflected = bandRadiance(290);
  const lowE = surfaceRadiance(320, 0.3, reflected);
  const highE = surfaceRadiance(320, 0.9, reflected);
  assert.ok(highE > lowE);
  const crossoverObject = surfaceRadiance(300, 0.4, bandRadiance(300));
  const crossoverBackground = surfaceRadiance(300, 0.95, bandRadiance(300));
  assert.ok(Math.abs(crossoverObject - crossoverBackground) < 1e-9);
});

test("seeded detector noise is repeatable and display palette cannot alter raw radiance", () => {
  const clean = new Float32Array([0, 12, 18, 24, 30, 40]);
  const validity = new Uint8Array([0, 1, 1, 1, 1, 1]);
  const first = radianceRaster(clean, validity, { seed: 481, noise_sigma: 0.02, saturation_w_per_m2_sr: 35 });
  const second = radianceRaster(clean, validity, { seed: 481, noise_sigma: 0.02, saturation_w_per_m2_sr: 35 });
  const changed = radianceRaster(clean, validity, { seed: 482, noise_sigma: 0.02, saturation_w_per_m2_sr: 35 });
  assert.deepEqual(first, second);
  assert.notDeepEqual(first.radiance, changed.radiance);
  assert.equal(first.radiance[0], 0);
  assert.equal(first.saturation[5], 1);
  const before = new Uint8Array(first.radiance.buffer.slice(0));
  const preview = thermalPreviewRgba(first.radiance, validity, {
    min_w_per_m2_sr: 10,
    max_w_per_m2_sr: 40,
    palette: "iron-v1",
  });
  assert.equal(preview.length, clean.length * 4);
  assert.deepEqual(new Uint8Array(first.radiance.buffer), before);
});
