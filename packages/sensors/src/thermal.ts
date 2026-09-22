import type {
  AssetRecord,
  EnvironmentSpec,
  WorldSpec,
} from "@yulab/contracts";

export const THERMAL_MODEL_VERSION = "thermal-surface.v1";
export const THERMAL_STATE_VERSION = "thermal-state.v1";
export const LWIR_RESPONSE_VERSION = "lwir-8-14um.v1";
export const THERMAL_STEP_S = 1;
export const LWIR_BAND_UM = [8, 14] as const;

const STEFAN_BOLTZMANN = 5.670374419e-8;
const PLANCK = 6.62607015e-34;
const LIGHT = 299_792_458;
const BOLTZMANN = 1.380649e-23;
const SOLAR_IRRADIANCE_W_PER_M2 = 800;

export type SurfaceEnergyParameters = {
  emissivity: number;
  solar_absorption: number;
  thermal_capacity_j_per_k: number;
  area_m2: number;
  convection_w_per_m2_k: number;
  source_power_w: number;
  solar_irradiance_w_per_m2: number;
  air_temperature_k: number;
  environment_temperature_k: number;
};

export type ThermalNode = {
  instance_id: string;
  asset_id: string;
  region_id: string;
  temperature_k: number;
};

export type ThermalState = {
  version: typeof THERMAL_STATE_VERSION;
  thermal_model_version: typeof THERMAL_MODEL_VERSION;
  simulation_time_s: number;
  ambient_temperature_k: number;
  nodes: ThermalNode[];
};

type RegionDefinition = Omit<
  SurfaceEnergyParameters,
  | "source_power_w"
  | "solar_irradiance_w_per_m2"
  | "air_temperature_k"
  | "environment_temperature_k"
> & { source_power_w: number };

function assertFinitePositive(name: string, value: number, allowZero = false) {
  if (!Number.isFinite(value) || (allowZero ? value < 0 : value <= 0))
    throw new Error(`${name} must be ${allowZero ? "non-negative" : "positive"} and finite`);
}

function energyRate(temperatureK: number, node: SurfaceEnergyParameters) {
  const convection = node.convection_w_per_m2_k * node.area_m2 *
    (temperatureK - node.air_temperature_k);
  const radiation = node.emissivity * STEFAN_BOLTZMANN * node.area_m2 *
    (temperatureK ** 4 - node.environment_temperature_k ** 4);
  const solar = node.solar_absorption * node.area_m2 *
    node.solar_irradiance_w_per_m2;
  return node.source_power_w + solar - convection - radiation;
}

function validateEnergyParameters(node: SurfaceEnergyParameters) {
  if (!Number.isFinite(node.emissivity) || node.emissivity < 0 || node.emissivity > 1)
    throw new Error("Emissivity must be in 0..1");
  if (!Number.isFinite(node.solar_absorption) || node.solar_absorption < 0 || node.solar_absorption > 1)
    throw new Error("Solar absorption must be in 0..1");
  assertFinitePositive("Thermal capacity", node.thermal_capacity_j_per_k);
  assertFinitePositive("Area", node.area_m2);
  assertFinitePositive("Convection", node.convection_w_per_m2_k, true);
  assertFinitePositive("Source power", node.source_power_w, true);
  assertFinitePositive("Solar irradiance", node.solar_irradiance_w_per_m2, true);
  assertFinitePositive("Air temperature", node.air_temperature_k);
  assertFinitePositive("Environment temperature", node.environment_temperature_k);
}

export function equilibriumTemperature(node: SurfaceEnergyParameters) {
  validateEnergyParameters(node);
  let low = 1;
  let high = Math.max(2_000, node.air_temperature_k * 2);
  while (energyRate(high, node) > 0 && high < 10_000) high *= 1.5;
  if (energyRate(low, node) < 0 || energyRate(high, node) > 0)
    throw new Error("Thermal equilibrium is outside the supported temperature range");
  for (let i = 0; i < 96; i++) {
    const middle = (low + high) / 2;
    if (energyRate(middle, node) > 0) low = middle;
    else high = middle;
  }
  return (low + high) / 2;
}

/** One deterministic RK4 integration step of the documented surface energy balance. */
export function stepSurfaceTemperature(
  temperatureK: number,
  node: SurfaceEnergyParameters,
  timestepS: number,
) {
  assertFinitePositive("Surface temperature", temperatureK);
  validateEnergyParameters(node);
  assertFinitePositive("Thermal timestep", timestepS);
  if (timestepS > THERMAL_STEP_S)
    throw new Error(`Thermal timestep must not exceed ${THERMAL_STEP_S} s`);
  const derivative = (temperature: number) =>
    energyRate(temperature, node) / node.thermal_capacity_j_per_k;
  const k1 = derivative(temperatureK);
  const k2 = derivative(temperatureK + timestepS * k1 / 2);
  const k3 = derivative(temperatureK + timestepS * k2 / 2);
  const k4 = derivative(temperatureK + timestepS * k3);
  const next = temperatureK + timestepS * (k1 + 2 * k2 + 2 * k3 + k4) / 6;
  if (!Number.isFinite(next) || next <= 0)
    throw new Error("Thermal integration produced an invalid temperature");
  return next;
}

function operatingFraction(state: WorldSpec["instances"][number]["operating_state"]) {
  return state === "running" ? 1 : state === "idle" ? 0.25 : 0;
}

function regions(record: AssetRecord) {
  if (record.thermal_model_version !== THERMAL_MODEL_VERSION)
    throw new Error(`${record.asset_id}: unsupported thermal model version`);
  const materialById = new Map(record.materials.map((material) => [material.id, material]));
  const sourceByPart = new Map(record.heat_sources.map((source) => [source.part_id, source]));
  const grouped = new Map<string, RegionDefinition>();
  for (const part of record.parts) {
    const material = materialById.get(part.material_id);
    if (!material) throw new Error(`${record.asset_id}:${part.id}: thermal material missing`);
    const current = grouped.get(part.semantic) ?? {
      emissivity: 0,
      solar_absorption: 0,
      thermal_capacity_j_per_k: 0,
      area_m2: 0,
      convection_w_per_m2_k: 0,
      source_power_w: 0,
    };
    current.emissivity += material.emissivity * material.area_m2;
    current.solar_absorption += material.solar_absorption * material.area_m2;
    current.thermal_capacity_j_per_k += material.thermal_capacity_j_per_k;
    current.convection_w_per_m2_k += material.convection_w_per_m2_k * material.area_m2;
    current.area_m2 += material.area_m2;
    current.source_power_w += sourceByPart.get(part.id)?.power_w ?? 0;
    grouped.set(part.semantic, current);
  }
  return [...grouped.entries()].map(([region_id, value]) => ({
    region_id,
    definition: {
      ...value,
      emissivity: value.emissivity / value.area_m2,
      solar_absorption: value.solar_absorption / value.area_m2,
      convection_w_per_m2_k: value.convection_w_per_m2_k / value.area_m2,
    },
  })).sort((a, b) => a.region_id.localeCompare(b.region_id));
}

function solarIrradiance(environment: EnvironmentSpec) {
  const [x, y, z] = environment.sun_direction_world;
  const length = Math.hypot(x, y, z);
  if (length === 0) return 0;
  return SOLAR_IRRADIANCE_W_PER_M2 * Math.max(0, y / length);
}

function energyParameters(
  definition: RegionDefinition,
  state: WorldSpec["instances"][number]["operating_state"],
  environment: EnvironmentSpec,
): SurfaceEnergyParameters {
  return {
    ...definition,
    source_power_w: definition.source_power_w * operatingFraction(state),
    solar_irradiance_w_per_m2: solarIrradiance(environment),
    air_temperature_k: environment.ambient_temperature_k,
    environment_temperature_k: environment.ambient_temperature_k,
  };
}

function modelEntries(world: WorldSpec, assets: readonly AssetRecord[]) {
  const byId = new Map(assets.map((asset) => [asset.asset_id, asset]));
  return world.instances.flatMap((instance) => {
    const record = byId.get(instance.asset_id);
    if (!record || record.content_sha256 !== instance.asset_sha256)
      throw new Error(`${instance.instance_id}: thermal asset identity mismatch`);
    return regions(record).map((region) => ({ instance, ...region }));
  }).sort((a, b) =>
    a.instance.instance_id.localeCompare(b.instance.instance_id) ||
    a.region_id.localeCompare(b.region_id),
  );
}

export function initializeThermalState(
  world: WorldSpec,
  assets: readonly AssetRecord[],
  environment: EnvironmentSpec,
): ThermalState {
  return {
    version: THERMAL_STATE_VERSION,
    thermal_model_version: THERMAL_MODEL_VERSION,
    simulation_time_s: environment.simulation_time_s,
    ambient_temperature_k: environment.ambient_temperature_k,
    nodes: modelEntries(world, assets).map(({ instance, region_id, definition }) => ({
      instance_id: instance.instance_id,
      asset_id: instance.asset_id,
      region_id,
      temperature_k: equilibriumTemperature(
        energyParameters(definition, instance.operating_state, environment),
      ),
    })),
  };
}

function validateState(state: ThermalState) {
  if (state.version !== THERMAL_STATE_VERSION)
    throw new Error(`Unsupported thermal state version: ${String(state.version)}`);
  if (state.thermal_model_version !== THERMAL_MODEL_VERSION)
    throw new Error(`Unsupported thermal model version: ${String(state.thermal_model_version)}`);
  assertFinitePositive("Thermal state time", state.simulation_time_s, true);
  assertFinitePositive("Thermal ambient temperature", state.ambient_temperature_k);
  if (!Array.isArray(state.nodes)) throw new Error("Thermal state nodes must be an array");
  const identities = new Set<string>();
  for (const node of state.nodes) {
    const identity = `${node.instance_id}\0${node.region_id}`;
    if (!node.instance_id || !node.asset_id || !node.region_id || identities.has(identity))
      throw new Error("Thermal state node identity is invalid or duplicated");
    identities.add(identity);
    assertFinitePositive("Thermal node temperature", node.temperature_k);
  }
}

export function advanceThermalState(
  state: ThermalState,
  world: WorldSpec,
  assets: readonly AssetRecord[],
  environment: EnvironmentSpec,
): ThermalState {
  validateState(state);
  if (environment.simulation_time_s < state.simulation_time_s)
    throw new Error("Thermal state cannot evolve backward in time");
  const entries = modelEntries(world, assets);
  const existing = new Map(state.nodes.map((node) => [
    `${node.instance_id}\0${node.region_id}`,
    node,
  ]));
  const nodes = entries.map(({ instance, region_id, definition }) => {
    const prior = existing.get(`${instance.instance_id}\0${region_id}`);
    if (!prior || prior.asset_id !== instance.asset_id)
      throw new Error(`${instance.instance_id}:${region_id}: thermal state node missing`);
    const parameters = energyParameters(definition, instance.operating_state, environment);
    let temperature = prior.temperature_k;
    let remaining = environment.simulation_time_s - state.simulation_time_s;
    while (remaining > 1e-12) {
      const step = Math.min(THERMAL_STEP_S, remaining);
      temperature = stepSurfaceTemperature(temperature, parameters, step);
      remaining -= step;
    }
    return {
      instance_id: instance.instance_id,
      asset_id: instance.asset_id,
      region_id,
      temperature_k: temperature,
    };
  });
  return {
    version: THERMAL_STATE_VERSION,
    thermal_model_version: THERMAL_MODEL_VERSION,
    simulation_time_s: environment.simulation_time_s,
    ambient_temperature_k: environment.ambient_temperature_k,
    nodes,
  };
}

export function encodeThermalState(state: ThermalState) {
  validateState(state);
  return `${JSON.stringify({
    ...state,
    nodes: [...state.nodes].sort((a, b) =>
      a.instance_id.localeCompare(b.instance_id) || a.region_id.localeCompare(b.region_id),
    ),
  }, null, 2)}\n`;
}

export function decodeThermalState(text: string) {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("Thermal state is not valid JSON");
  }
  const state = parsed as ThermalState;
  validateState(state);
  return state;
}

/** Band-integrated blackbody radiance in W/(m2 sr), using 8..14 um response v1. */
export function bandRadiance(temperatureK: number) {
  assertFinitePositive("Radiating temperature", temperatureK);
  const [lowUm, highUm] = LWIR_BAND_UM;
  const intervals = 120;
  const stepM = (highUm - lowUm) * 1e-6 / intervals;
  const spectral = (wavelengthM: number) => {
    const numerator = 2 * PLANCK * LIGHT ** 2;
    const exponent = PLANCK * LIGHT / (wavelengthM * BOLTZMANN * temperatureK);
    return numerator / (wavelengthM ** 5 * Math.expm1(exponent));
  };
  let sum = 0;
  for (let i = 0; i <= intervals; i++) {
    const wavelength = lowUm * 1e-6 + i * stepM;
    sum += spectral(wavelength) * (i === 0 || i === intervals ? 1 : i % 2 ? 4 : 2);
  }
  return sum * stepM / 3;
}

export function surfaceRadiance(
  temperatureK: number,
  emissivity: number,
  reflectedRadiance: number,
) {
  if (!Number.isFinite(emissivity) || emissivity < 0 || emissivity > 1)
    throw new Error("Emissivity must be in 0..1");
  assertFinitePositive("Reflected radiance", reflectedRadiance, true);
  return emissivity * bandRadiance(temperatureK) + (1 - emissivity) * reflectedRadiance;
}

function noiseSample(seed: number, index: number) {
  let value = (seed ^ Math.imul(index + 1, 0x9e3779b1)) >>> 0;
  const uniform = () => {
    value += 0x6d2b79f5;
    let x = value;
    x = Math.imul(x ^ x >>> 15, x | 1);
    x ^= x + Math.imul(x ^ x >>> 7, x | 61);
    return ((x ^ x >>> 14) >>> 0) / 4294967296;
  };
  const u1 = Math.max(Number.EPSILON, uniform());
  const u2 = uniform();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

export function radianceRaster(
  clean: Float32Array,
  validity: Uint8Array,
  response: { seed: number; noise_sigma: number; saturation_w_per_m2_sr: number },
) {
  if (clean.length !== validity.length) throw new Error("IR raster shapes differ");
  if (!Number.isInteger(response.seed) || response.seed < 0 || response.seed > 0xffff_ffff)
    throw new Error("IR noise seed must be uint32");
  assertFinitePositive("IR noise sigma", response.noise_sigma, true);
  assertFinitePositive("IR saturation", response.saturation_w_per_m2_sr);
  const radiance = new Float32Array(clean.length);
  const saturation = new Uint8Array(clean.length);
  for (let i = 0; i < clean.length; i++) {
    if (!validity[i]) continue;
    const noisy = Math.max(0, clean[i] + response.noise_sigma * noiseSample(response.seed, i));
    saturation[i] = noisy >= response.saturation_w_per_m2_sr ? 1 : 0;
    radiance[i] = Math.min(noisy, response.saturation_w_per_m2_sr);
  }
  return { radiance, saturation };
}

export function thermalPreviewRgba(
  radiance: Float32Array,
  validity: Uint8Array,
  display: {
    min_w_per_m2_sr: number;
    max_w_per_m2_sr: number;
    palette: "iron-v1";
  },
) {
  if (radiance.length !== validity.length) throw new Error("IR preview shapes differ");
  if (
    display.palette !== "iron-v1" ||
    !Number.isFinite(display.min_w_per_m2_sr) ||
    !Number.isFinite(display.max_w_per_m2_sr) ||
    display.max_w_per_m2_sr <= display.min_w_per_m2_sr
  ) throw new Error("Invalid IR preview configuration");
  const output = new Uint8Array(radiance.length * 4);
  for (let i = 0; i < radiance.length; i++) {
    const offset = i * 4;
    if (validity[i]) {
      const t = Math.max(0, Math.min(1,
        (radiance[i] - display.min_w_per_m2_sr) /
        (display.max_w_per_m2_sr - display.min_w_per_m2_sr),
      ));
      output[offset] = Math.round(255 * Math.min(1, t * 3));
      output[offset + 1] = Math.round(255 * Math.max(0, Math.min(1, t * 3 - 1)));
      output[offset + 2] = Math.round(255 * Math.max(0, t * 3 - 2));
    }
    output[offset + 3] = 255;
  }
  return output;
}
