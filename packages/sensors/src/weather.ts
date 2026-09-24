import type { EnvironmentSpec } from "@yulab/contracts";
import { bandRadiance } from "./thermal.ts";

export const WEATHER_RESPONSE_VERSION = "weather-response.v1";
export type WeatherPreset = "clear-day" | "night" | "fog" | "rain" | "snow" | "hot-background";

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

/** Synthetic, versioned conditions. Clock and sun are shared by all sensor passes. */
export function environmentPreset(
  preset: WeatherPreset, severity: number, solarTimeHour: number, simulationTimeS: number,
): EnvironmentSpec {
  if (!Number.isFinite(severity) || severity < 0 || severity > 1 ||
      !Number.isFinite(solarTimeHour) || solarTimeHour < 0 || solarTimeHour > 24 ||
      !Number.isFinite(simulationTimeS) || simulationTimeS < 0)
    throw new Error("Invalid environment severity or clock");
  const angle = Math.PI * (solarTimeHour - 6) / 12;
  const sunY = Math.sin(angle);
  const sunX = Math.cos(angle);
  return {
    schema_version: "lab.v1", kind: "EnvironmentSpec", environment_id: preset,
    simulation_time_s: simulationTimeS, solar_time_hour: solarTimeHour,
    latitude_rad: 0.9, sun_direction_world: [sunX, sunY, 0],
    ambient_temperature_k: preset === "hot-background" ? 293.15 + 35 * severity
      : preset === "snow" ? 293.15 - 20 * severity : 293.15,
    fog_extinction_per_m: preset === "fog" ? 0.006 * severity : 0,
    rain_mm_per_h: preset === "rain" ? 45 * severity : 0,
    snow_mm_per_h: preset === "snow" ? 24 * severity : 0,
    wind_m_per_s: preset === "rain" || preset === "snow" ? [3 * severity, 0, 0] : [0, 0, 0],
    wetness: preset === "rain" ? severity : 0,
    parameter_set_version: WEATHER_RESPONSE_VERSION,
    thermal_history: "equilibrated", thermal_state: null,
  };
}

/** Per-metre coefficients are spectral approximations, not measured weather calibration. */
export function weatherResponse(environment: EnvironmentSpec) {
  const fog = environment.fog_extinction_per_m;
  const rain = environment.rain_mm_per_h;
  const snow = environment.snow_mm_per_h;
  const daylight = clamp(environment.sun_direction_world[1], 0, 1);
  return {
    version: WEATHER_RESPONSE_VERSION as typeof WEATHER_RESPONSE_VERSION,
    rgb_extinction_per_m: fog + rain * 0.000035 + snow * 0.00011,
    ir_extinction_per_m: fog * 0.22 + rain * 0.000018 + snow * 0.000045,
    lidar_extinction_per_m: fog * 0.8 + rain * 0.000045 + snow * 0.00013,
    rgb_illumination: 0.08 + 0.92 * daylight,
    rgb_read_sigma_dn: 2,
    rgb_shot_sigma_scale: 0.25,
    rgb_blur_mix: clamp(rain / 45 * 0.25 + snow / 24 * 0.4, 0, 0.7),
    particle_rate_per_m: rain * 0.000015 + snow * 0.000035,
    ir_path_radiance_w_per_m2_sr: bandRadiance(environment.ambient_temperature_k),
    ir_noise_sigma_w_per_m2_sr: 0.02 + rain * 0.0003 + snow * 0.0004,
  };
}

/** Stateless counter-based samples keep modality and weather streams independent. */
export function weatherUniform(seed: number, index: number, stream: number) {
  let x = (seed ^ Math.imul(index + 1, 0x9e3779b1) ^ Math.imul(stream + 1, 0x85ebca6b)) >>> 0;
  x ^= x >>> 16; x = Math.imul(x, 0x7feb352d); x ^= x >>> 15;
  x = Math.imul(x, 0x846ca68b); x ^= x >>> 16;
  return ((x >>> 0) + 0.5) / 4294967296;
}

export function weatherGaussian(seed: number, index: number, stream: number) {
  return Math.sqrt(-2 * Math.log(weatherUniform(seed, index, stream))) *
    Math.cos(2 * Math.PI * weatherUniform(seed, index, stream + 1));
}

export function applyIrAtmosphere(surfaceRadiance: number, distanceM: number,
  response: ReturnType<typeof weatherResponse>) {
  const tau = Math.exp(-response.ir_extinction_per_m * Math.max(0, distanceM));
  return tau * surfaceRadiance + (1 - tau) * response.ir_path_radiance_w_per_m2_sr;
}

/** Fixed-exposure RGB observation. Geometric depth and instance references stay clean. */
export function applyRgbWeather(
  source: Uint8Array, depth: Float32Array, width: number, height: number,
  environment: EnvironmentSpec, sensorSeed: number, weatherSeed: number,
) {
  if (source.length !== width * height * 4 || depth.length !== width * height)
    throw new Error("RGB weather raster shapes differ");
  const response = weatherResponse(environment);
  const output = new Uint8Array(source.length);
  const airlight = [184, 193, 201];
  for (let i = 0; i < depth.length; i++) {
    const x = i % width, y = Math.floor(i / width), offset = i * 4;
    const distance = depth[i] > 0 ? depth[i] : 250;
    const tau = Math.exp(-response.rgb_extinction_per_m * distance);
    const particleProbability = 1 - Math.exp(-response.particle_rate_per_m * Math.min(distance, 120));
    const particle = weatherUniform(weatherSeed, i, 0) < particleProbability;
    const snow = environment.snow_mm_per_h > 0;
    for (let channel = 0; channel < 3; channel++) {
      let scene = source[offset + channel];
      if (response.rgb_blur_mix > 0 && depth[i] > 0) {
        let sum = 0, count = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const px = x + dx, py = y + dy;
          if (px < 0 || py < 0 || px >= width || py >= height) continue;
          const j = py * width + px;
          if (Math.abs(depth[j] - depth[i]) > 2) continue;
          sum += source[j * 4 + channel]; count++;
        }
        scene = scene * (1 - response.rgb_blur_mix) + sum / count * response.rgb_blur_mix;
      }
      let signal = (scene * tau + airlight[channel] * (1 - tau)) * response.rgb_illumination;
      if (particle) signal = signal * (snow ? 0.35 : 0.55) + (snow ? 230 : 165) * (snow ? 0.65 : 0.45);
      const sigma = Math.hypot(response.rgb_read_sigma_dn,
        response.rgb_shot_sigma_scale * Math.sqrt(Math.max(0, signal)));
      output[offset + channel] = Math.round(clamp(signal + sigma * weatherGaussian(sensorSeed, i, channel * 2), 0, 255));
    }
    output[offset + 3] = 255;
  }
  return output;
}
