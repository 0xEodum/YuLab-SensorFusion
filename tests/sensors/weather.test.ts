import test from "node:test";
import assert from "node:assert/strict";
import {
  environmentPreset,
  weatherResponse,
  applyRgbWeather,
  applyIrAtmosphere,
} from "../../packages/sensors/src/weather.ts";
import * as THREE from "three";
import { cameraPoseToRig } from "../../packages/sensors/src/index.ts";
import { buildLidarScene, scanLidar, LIDAR_STATUS } from "../../packages/sensors/src/lidar.ts";
import { bandRadiance } from "../../packages/sensors/src/thermal.ts";

function interval(values: number[]) {
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
    (values.length - 1);
  return { mean, lower: mean - 1.96 * Math.sqrt(variance / values.length),
    upper: mean + 1.96 * Math.sqrt(variance / values.length) };
}

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
  const object = bandRadiance(330), engine = bandRadiance(450);
  const coolContrast = object - bandRadiance(293.15);
  const crossoverContrast = Math.abs(object - bandRadiance(hot.ambient_temperature_k));
  assert.ok(crossoverContrast < coolContrast * 0.25);
  assert.ok(engine - bandRadiance(hot.ambient_temperature_k) > coolContrast);
});

test("30 fixed seeds show RGB contrast and SNR losses with confidence intervals", (context) => {
  const width = 32, height = 32;
  const rgba = new Uint8Array(width * height * 4);
  const depth = new Float32Array(width * height).fill(90);
  for (let i = 0; i < width * height; i++)
    rgba.set([i % width < width / 2 ? 160 : 80, 100, 90, 255], i * 4);
  const conditions = [environmentPreset("clear-day", 0, 12, 0),
    environmentPreset("night", 1, 0, 0), environmentPreset("fog", 1, 12, 0)];
  const contrast: number[][] = conditions.map(() => []);
  const snr: number[][] = conditions.map(() => []);
  for (let seed = 0; seed < 30; seed++) conditions.forEach((condition, index) => {
    const pixels = applyRgbWeather(rgba, depth, width, height, condition, seed, seed);
    const groups: number[][] = [[], []];
    for (let i = 0; i < width * height; i++) groups[i % width < width / 2 ? 0 : 1].push(pixels[i * 4]);
    const means = groups.map((group) => group.reduce((sum, value) => sum + value, 0) / group.length);
    const noise = Math.sqrt(groups.reduce((sum, group, g) => sum +
      group.reduce((part, value) => part + (value - means[g]) ** 2, 0), 0) /
      (width * height - 2));
    contrast[index].push(means[0] - means[1]);
    snr[index].push((means[0] - means[1]) / noise);
  });
  const contrastDrop = interval(contrast[0].map((value, i) => value - contrast[2][i]));
  const snrDrop = interval(snr[0].map((value, i) => value - snr[1][i]));
  context.diagnostic(JSON.stringify({ seeds: 30, fog_contrast_loss_dn: contrastDrop,
    night_snr_loss: snrDrop }));
  assert.ok(contrastDrop.lower > 0);
  assert.ok(snrDrop.lower > 0);
});

test("30 fixed seeds show LiDAR surface loss and precipitation particles", (context) => {
  const rig = cameraPoseToRig({ rigId: "weather", position: [0, 0, 0],
    quaternion: [0, 0, 0, 1], width: 640, height: 384, verticalFovRadians: 0.7 });
  const sensor = rig.sensors.find((item) => item.modality === "lidar")!;
  sensor.available = true;
  sensor.lidar!.rows = 1;
  sensor.lidar!.columns = 128;
  sensor.max_range_m = 150;
  const scene = new THREE.Scene();
  const wall = new THREE.Mesh(new THREE.BoxGeometry(180, 100, 1), new THREE.MeshBasicMaterial());
  wall.position.z = -90;
  scene.add(wall);
  const geometry = buildLidarScene(scene);
  const clear = environmentPreset("clear-day", 0, 12, 0);
  const fog = environmentPreset("fog", 1, 12, 0);
  const rain = environmentPreset("rain", 1, 12, 0);
  const snow = environmentPreset("snow", 1, 12, 0);
  const losses: number[] = [];
  let rainParticles = 0, snowParticles = 0;
  for (let seed = 0; seed < 30; seed++) {
    const options = (environment: typeof clear) => ({ environment, weather_seed: seed,
      range_sigma_m: 0, intensity_sigma: 0 });
    const clean = scanLidar(geometry, rig, seed, options(clear));
    const adverse = scanLidar(geometry, rig, seed, options(fog));
    const rainScan = scanLidar(geometry, rig, seed, options(rain));
    const snowScan = scanLidar(geometry, rig, seed, options(snow));
    assert.deepEqual(clean.ideal_hits.map((hit) => hit?.range_m),
      adverse.ideal_hits.map((hit) => hit?.range_m));
    losses.push(clean.beam_status.filter((status) => status === LIDAR_STATUS.surface).length -
      adverse.beam_status.filter((status) => status === LIDAR_STATUS.surface).length);
    rainParticles += rainScan.beam_status.filter((status) => status === LIDAR_STATUS.particle).length;
    snowParticles += snowScan.beam_status.filter((status) => status === LIDAR_STATUS.particle).length;
  }
  geometry.dispose();
  const surfaceLoss = interval(losses);
  context.diagnostic(JSON.stringify({ seeds: 30, fog_surface_return_loss: surfaceLoss,
    rain_particles: rainParticles, snow_particles: snowParticles }));
  assert.ok(surfaceLoss.lower > 0);
  assert.ok(rainParticles > 0 && snowParticles > 0);
});
