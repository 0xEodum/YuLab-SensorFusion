import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { AssetLibrary, validateCatalog } from "@yulab/assets";
import { aerodromeWorldSpec, harborWorldSpec } from "@yulab/world";
import { initializeThermalState } from "@yulab/sensors/thermal";
import type { EnvironmentSpec } from "@yulab/contracts";

const base = new URL("../../frontend/public/catalog/", import.meta.url);
const catalog = validateCatalog(JSON.parse(readFileSync(new URL("catalog.json", base), "utf8")));

test("catalog vehicle engine states vary by seed and drive distinct thermal signatures", () => {
  const states = new Set<string>();
  const temperatures = new Set<string>();
  const environment: EnvironmentSpec = {
    schema_version: "lab.v1", kind: "EnvironmentSpec", environment_id: "vehicle-variation",
    simulation_time_s: 0, solar_time_hour: 0, latitude_rad: 0,
    sun_direction_world: [0, 0, 0], ambient_temperature_k: 293.15,
    fog_extinction_per_m: 0, rain_mm_per_h: 0, snow_mm_per_h: 0,
    wind_m_per_s: [0, 0, 0], wetness: 0,
    parameter_set_version: "thermal-clear.v1", thermal_history: "equilibrated",
    thermal_state: null,
  };
  for (let seed = 0; seed < 32; seed++) {
    const world = aerodromeWorldSpec(seed, catalog.assets, "catalog");
    assert.deepEqual(world, aerodromeWorldSpec(seed, catalog.assets, "catalog"));
    const thermal = initializeThermalState(world, catalog.assets, environment);
    for (const instance of world.instances) {
      states.add(instance.operating_state);
      const engine = thermal.nodes.find((node) =>
        node.instance_id === instance.instance_id && node.region_id === "engine-surface");
      assert.ok(engine, instance.instance_id);
      temperatures.add(engine.temperature_k.toFixed(3));
    }
  }
  assert.deepEqual([...states].sort(), ["idle", "off", "running"]);
  assert.ok(temperatures.size >= 3);
  const shipStates = new Set(Array.from({ length: 32 }, (_, seed) =>
    harborWorldSpec(seed, catalog.assets).instances.slice(0, 2)
      .map((instance) => instance.operating_state)).flat());
  assert.deepEqual([...shipStates].sort(), ["idle", "off", "running"]);
});

test("authored anti-aircraft turrets rotate independently with stable instance poses", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const path = String(input);
    assert.match(path, /^\/catalog\/(ground-vehicle|spaa)\.(glb|metadata\.json)$/);
    return new Response(readFileSync(new URL(path.slice("/catalog/".length), base)));
  };
  const library = new AssetLibrary(catalog);
  try {
    const world = aerodromeWorldSpec(5, catalog.assets, "catalog");
    world.instances = ["ground-vehicle", "spaa"].map((id, index) => ({
      instance_id: `turret-${id}-${index}`,
      asset_id: id,
      asset_sha256: catalog.assets.find((asset) => asset.asset_id === id)!.content_sha256,
      T_world_from_asset: [1, 0, 0, index * 20, 0, 1, 0, 24.04,
        0, 0, 1, 0, 0, 0, 0, 1],
      operating_state: "off" as const,
    }));
    await library.load(world, AbortSignal.timeout(30_000));
    for (const instance of world.instances) {
      const a = library.instantiate(instance);
      const b = library.instantiate(instance);
      const turret = a.getObjectByName("turret-yaw");
      assert.ok(turret, instance.asset_id);
      assert.ok(turret.children.length > 0, instance.asset_id);
      assert.equal(turret.rotation.y, b.getObjectByName("turret-yaw")!.rotation.y);
      assert.ok(Math.abs(turret.rotation.y) <= Math.PI);
      assert.equal(turret.position.y > 1.8, true);
    }
    const angles = world.instances.map((instance) =>
      library.instantiate(instance).getObjectByName("turret-yaw")!.rotation.y);
    assert.notEqual(angles[0], angles[1]);
  } finally {
    library.dispose();
    globalThis.fetch = originalFetch;
  }
});
