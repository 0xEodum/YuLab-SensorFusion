import test from "node:test";
import assert from "node:assert/strict";
import {
  environmentPreset,
  weatherResponse,
  applyRgbWeather,
  applyIrAtmosphere,
} from "../../packages/sensors/src/weather.ts";

test("presets share one frozen clock and severity with distinct spectral response", () => {
  const rain = environmentPreset("rain", 0.7, 18, 3600);
  assert.equal(rain.simulation_time_s, 3600);
  assert.equal(rain.solar_time_hour, 18);
  assert.equal(rain.thermal_history, "equilibrated");
  assert.ok(rain.rain_mm_per_h > 0);
  const response = weatherResponse(rain);
  assert.ok(response.rgb_extinction_per_m > 0);
  assert.ok(response.ir_extinction_per_m > 0);
  assert.ok(response.lidar_extinction_per_m > 0);
  assert.notEqual(response.rgb_extinction_per_m, response.ir_extinction_per_m);
  assert.ok(environmentPreset("night", 1, 0, 0).sun_direction_world[1] < 0);
});

test("RGB sensor seed changes only read noise; weather seed changes only particles", () => {
  const env = environmentPreset("snow", 0.8, 12, 0);
  const rgba = new Uint8Array(16 * 16 * 4);
  const depth = new Float32Array(16 * 16).fill(80);
  for (let i = 0; i < rgba.length; i += 4) rgba.set([120, 90, 60, 255], i);
  const a = applyRgbWeather(rgba, depth, 16, 16, env, 3, 7);
  const b = applyRgbWeather(rgba, depth, 16, 16, env, 3, 7);
  const sensor = applyRgbWeather(rgba, depth, 16, 16, env, 4, 7);
  const weather = applyRgbWeather(rgba, depth, 16, 16, env, 3, 8);
  assert.deepEqual(a, b);
  assert.notDeepEqual(a, sensor);
  assert.notDeepEqual(a, weather);
  assert.deepEqual(rgba.slice(0, 4), new Uint8Array([120, 90, 60, 255]));
});

test("LWIR path attenuation includes path emission and thermal crossover is local", () => {
  const env = environmentPreset("fog", 1, 12, 0);
  const response = weatherResponse(env);
  const background = response.ir_path_radiance_w_per_m2_sr;
  const near = applyIrAtmosphere(background + 20, 1, response);
  const far = applyIrAtmosphere(background + 20, 200, response);
  assert.ok(near > far);
  assert.ok(far > background);
  const hot = environmentPreset("hot-background", 1, 12, 0);
  assert.ok(hot.ambient_temperature_k > env.ambient_temperature_k);
});
