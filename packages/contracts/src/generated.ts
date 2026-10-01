/* Generated from contracts/lab.schema.json. Do not edit. */

/**
 * Canonical lab.v1 wire shapes. SF-05 adds backend-owned RGB/reference capture jobs.
 */
export type LabPayload =
  | AssetRecord
  | WorldSpec
  | RigSpec
  | EnvironmentSpec
  | CapturePlan
  | CaptureRequest
  | CaptureJob
  | ObservationBundle
  | AnnotationBundle
  | TruthBundle
  | DatasetManifest
  | PredictionBundle
  | Health
  | Capabilities
  | ApiError;
export type Id = string;
export type Hash = string;
export type Version = string;
/**
 * Row-major T_A_from_B acting on column vectors; translation in metres. Rigid rotation validated by the geometry stage.
 *
 * @minItems 16
 * @maxItems 16
 */
export type Transform = [
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  0,
  0,
  0,
  1
];
/**
 * @minItems 3
 * @maxItems 3
 */
export type Vec3 = [number, number, number];
/**
 * @minItems 4
 * @maxItems 4
 */
export type Quaternion = [number, number, number, number];
export type SensorRig = {
  sensor_id: Id;
  modality: "rgb" | "ir" | "lidar";
  available: boolean;
  T_rig_from_sensor: Transform;
  timestamp_offset_s: number;
  exposure_s: number;
  scan_duration_s: number;
  min_range_m: number;
  max_range_m: number;
  camera: Camera | null;
  lidar: Lidar | null;
  sensor_model_version: Version;
} & {
  sensor_id: Id;
  modality: "rgb" | "ir" | "lidar";
  available: boolean;
  T_rig_from_sensor: Transform;
  timestamp_offset_s: number;
  exposure_s: number;
  scan_duration_s: number;
  min_range_m: number;
  max_range_m: number;
  camera: Camera | null;
  lidar: Lidar | null;
  sensor_model_version: Version;
} & {
  sensor_id: Id;
  modality: "rgb" | "ir" | "lidar";
  available: boolean;
  T_rig_from_sensor: Transform;
  timestamp_offset_s: number;
  exposure_s: number;
  scan_duration_s: number;
  min_range_m: number;
  max_range_m: number;
  camera: Camera | null;
  lidar: Lidar | null;
  sensor_model_version: Version;
};
export type RgbObservation =
  | Unavailable
  | {
      status: "available";
      timestamp_s: number;
      health: "ok" | "degraded";
      sensor_id: Id;
      sensor_model_version: Version;
      data: RgbData;
    };
export type IrObservation =
  | Unavailable
  | {
      status: "available";
      timestamp_s: number;
      health: "ok" | "degraded";
      sensor_id: Id;
      sensor_model_version: Version;
      data: IrData;
    };
export type LidarObservation =
  | Unavailable
  | {
      status: "available";
      timestamp_s: number;
      health: "ok" | "degraded";
      sensor_id: Id;
      sensor_model_version: Version;
      data: LidarData;
    };
export type Capability = {
  available: boolean;
  reason: ("not_implemented" | "no_checkpoint" | "device_unavailable") | null;
};

export interface AssetRecord {
  schema_version: "lab.v1";
  kind: "AssetRecord";
  asset_id: Id;
  content_sha256: Hash;
  mesh: Artifact;
  metadata: Artifact;
  source: {
    project: string;
    revision: string;
    sha256: Hash;
    adapter_version: Version;
    use_permission: string;
  };
  units: Units;
  scale_m_per_source_unit: number;
  T_world_from_asset: Transform;
  contact_point_m: Vec3;
  class_name: "aircraft" | "ground_vehicle" | "ship" | "background";
  bounds: Box3;
  /**
   * @minItems 1
   * @maxItems 10000
   */
  parts: [Part, ...Part[]];
  /**
   * @minItems 1
   * @maxItems 1000
   */
  materials: [Material, ...Material[]];
  /**
   * @minItems 0
   * @maxItems 1000
   */
  heat_sources: HeatSource[];
  thermal_model_version: Version;
}
export interface Artifact {
  id: Id;
  sha256: Hash;
  byte_length: number;
  media_type: "model/gltf-binary" | "application/json" | "application/x-npy" | "image/png";
}
export interface Units {
  length: "m";
  temperature: "K";
  angle: "rad";
  time: "s";
  world_frame: "east-up-south";
  matrix_layout: "row-major";
}
export interface Box3 {
  frame: "east-up-south";
  center_m: Vec3;
  /**
   * @minItems 3
   * @maxItems 3
   */
  extent_m: [number, number, number];
  quaternion_xyzw: Quaternion;
}
export interface Part {
  id: Id;
  mesh_node: string;
  material_id: Id;
  semantic: string;
}
export interface Material {
  id: Id;
  emissivity: number;
  solar_absorption: number;
  thermal_capacity_j_per_k: number;
  area_m2: number;
  convection_w_per_m2_k: number;
  response_time_s: number;
  opaque_rgb: boolean;
  opaque_ir: boolean;
  opaque_lidar: boolean;
}
export interface HeatSource {
  part_id: Id;
  power_w: number;
  coupling_fraction: number;
  operating_state: "off" | "idle" | "running";
}
export interface WorldSpec {
  schema_version: "lab.v1";
  kind: "WorldSpec";
  world_id: Id;
  seed: number;
  units: Units;
  /**
   * @minItems 3
   * @maxItems 3
   */
  extent_m: [number, number, number];
  origin_m: Vec3;
  chunk_size_m: number;
  generator_version: Version;
  field_version: Version;
  /**
   * @minItems 0
   * @maxItems 1000
   */
  features: Feature[];
  /**
   * @minItems 0
   * @maxItems 100000
   */
  instances: Instance[];
}
export interface Feature {
  id: Id;
  type: "canyon" | "alpine" | "islands" | "coast" | "aerodrome" | "harbor";
  center_m: Vec3;
  /**
   * @minItems 3
   * @maxItems 3
   */
  extent_m: [number, number, number];
  seed: number;
}
export interface Instance {
  instance_id: Id;
  asset_id: Id;
  asset_sha256: Hash;
  T_world_from_asset: Transform;
  operating_state: "off" | "idle" | "running";
}
export interface RigSpec {
  schema_version: "lab.v1";
  kind: "RigSpec";
  rig_id: Id;
  calibration_version: Version;
  T_world_from_rig: Transform;
  /**
   * @minItems 3
   * @maxItems 3
   */
  sensors: [SensorRig, SensorRig, SensorRig];
  timing_profile: "synchronized-static" | "timed-scan";
}
export interface Camera {
  frame: "optical-right-down-forward";
  width_px: number;
  height_px: number;
  fx_px: number;
  fy_px: number;
  cx_px: number;
  cy_px: number;
  distortion: "ideal-pinhole";
}
export interface Lidar {
  frame: "lidar-forward-left-up";
  rows: number;
  columns: number;
  horizontal_fov_rad: number;
  vertical_fov_rad: number;
  return_policy: "single-first-opaque";
}
export interface EnvironmentSpec {
  schema_version: "lab.v1";
  kind: "EnvironmentSpec";
  environment_id: Id;
  simulation_time_s: number;
  solar_time_hour: number;
  latitude_rad: number;
  sun_direction_world: Vec3;
  ambient_temperature_k: number;
  fog_extinction_per_m: number;
  rain_mm_per_h: number;
  snow_mm_per_h: number;
  wind_m_per_s: Vec3;
  wetness: number;
  parameter_set_version: Version;
  thermal_history: "equilibrated" | "continued";
  thermal_state: Artifact | null;
}
export interface CapturePlan {
  schema_version: "lab.v1";
  kind: "CapturePlan";
  capture_id: Id;
  sequence_id: Id;
  world_sha256: Hash;
  rig_sha256: Hash;
  environment_sha256: Hash;
  simulation_time_s: number;
  geometry_policy: "fixed-sensor-geometry";
  quality_version: Version;
  seed_channels: {
    world: number;
    weather: number;
    rgb: number;
    ir: number;
    lidar: number;
  };
  /**
   * @minItems 1
   * @maxItems 3
   */
  modalities:
    | ["rgb" | "ir" | "lidar"]
    | ["rgb" | "ir" | "lidar", "rgb" | "ir" | "lidar"]
    | ["rgb" | "ir" | "lidar", "rgb" | "ir" | "lidar", "rgb" | "ir" | "lidar"];
}
export interface CaptureRequest {
  schema_version: "lab.v1";
  kind: "CaptureRequest";
  world: WorldSpec;
  rig: RigSpec;
  environment: EnvironmentSpec;
  plan: CapturePlan;
}
export interface CaptureJob {
  schema_version: "lab.v1";
  kind: "CaptureJob";
  job_id: Id;
  capture_id: Id;
  state: "queued" | "running" | "cancelling" | "cancelled" | "succeeded" | "failed";
  progress: number;
  result: CaptureResult | null;
  error: CaptureJobError | null;
  created_at: string;
  updated_at: string;
}
export interface CaptureResult {
  protocol: "capture-worker.v1";
  capture_id: Id;
  sequence_id: Id;
  tick_s: number;
  width: number;
  height: number;
  renderer: string;
  device: string;
  browser_channel: string;
  elapsed_ms: number;
  render_elapsed_ms: number;
  node_rss_bytes: number;
  browser_heap_bytes: number | null;
  gpu_memory_bytes: number | null;
  /**
   * @minItems 1
   * @maxItems 256
   */
  resident_chunks: [string, ...string[]];
  instance_ids: {
    [k: string]: number;
  };
  isolated_pixels?: {
    rgb: {
      [k: string]: number;
    };
    ir: {
      [k: string]: number;
    };
  };
  posed_boxes?: {
    [k: string]: Box3;
  };
  truncated?: {
    rgb: {
      [k: string]: boolean;
    };
    ir: {
      [k: string]: boolean;
    };
  };
  ir_calibration: IrCalibration | null;
  lidar_calibration: LidarCalibration | null;
  weather_calibration?: WeatherCalibration;
  environment?: EnvironmentSpec;
  plan?: CapturePlan;
  lidar_point_count: number;
  artifacts: CaptureArtifacts;
}
export interface IrCalibration {
  response_version: "lwir-8-14um.v1";
  /**
   * @minItems 2
   * @maxItems 2
   */
  band_um: [8, 14];
  radiance_units: "W/m2/sr";
  noise_sigma_w_per_m2_sr: number;
  saturation_w_per_m2_sr: number;
  thermal_model_version: "thermal-surface.v1";
  thermal_state_version: "thermal-state.v1";
  preview_palette: "iron-v1";
  /**
   * @minItems 2
   * @maxItems 2
   */
  preview_scale: [number, number];
  palette_applies_to_raw: false;
  atmosphere_version?: "weather-response.v1";
  extinction_per_m?: number;
  path_radiance_w_per_m2_sr?: number;
}
export interface LidarCalibration {
  version: "lidar-first-return.v1";
  sensor_id: Id;
  frame: "lidar-forward-left-up";
  rows: number;
  columns: number;
  horizontal_fov_rad: number;
  vertical_fov_rad: number;
  scan_duration_s: number;
  timestamp_offset_s: number;
  min_range_m: number;
  max_range_m: number;
  T_world_from_rig: Transform;
  T_rig_from_sensor: Transform;
  beam_order: "row-major; rows top-to-bottom, columns left-to-right";
  class_schema_version?: "lidar-semantic.v1";
  /**
   * @minItems 12
   * @maxItems 12
   */
  class_table?: [
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry,
    LidarClassEntry
  ];
  cloud_preview_projection?: "rgb-camera-perspective";
  topdown_preview_projection?: "lidar-sensor-overhead";
  status_codes: {
    no_return: 0;
    surface: 1;
    receiver_dropout: 2;
    particle?: 3;
    atmospheric_dropout?: 4;
  };
  response: {
    range_sigma_m: number;
    intensity_sigma: number;
    dropout_probability: number;
    intensity_model: "synthetic-incidence-exponential.v1";
    atmosphere_version?: "weather-response.v1" | null;
    extinction_per_m?: number;
    particle_rate_per_m?: number;
    detection_threshold?: number;
  };
}
export interface LidarClassEntry {
  id: number;
  name:
    | "unclassified"
    | "terrain"
    | "pavement"
    | "marking"
    | "building"
    | "vegetation"
    | "rock"
    | "fence"
    | "aircraft"
    | "ground_vehicle"
    | "ship"
    | "water";
  color: string;
}
export interface WeatherCalibration {
  version: "weather-response.v1";
  rgb_extinction_per_m: number;
  ir_extinction_per_m: number;
  lidar_extinction_per_m: number;
  rgb_illumination: number;
  rgb_read_sigma_dn: number;
  rgb_shot_sigma_scale: number;
  rgb_blur_mix: number;
  particle_rate_per_m: number;
  ir_path_radiance_w_per_m2_sr: number;
  ir_noise_sigma_w_per_m2_sr: number;
}
export interface CaptureArtifacts {
  rgb: Artifact;
  rgb_raw?: Artifact;
  ir_instance?: Artifact;
  depth_preview: Artifact;
  instance_preview: Artifact;
  depth: Artifact;
  instance: Artifact;
  ir_preview?: Artifact;
  ir_radiance?: Artifact;
  ir_validity?: Artifact;
  ir_saturation?: Artifact;
  thermal_state?: Artifact;
  lidar_xyz?: Artifact;
  lidar_intensity?: Artifact;
  lidar_beam_id?: Artifact;
  lidar_time_offset?: Artifact;
  lidar_validity?: Artifact;
  lidar_class_ref?: Artifact;
  lidar_beam_status?: Artifact;
  lidar_ideal_range?: Artifact;
  lidar_ideal_instance?: Artifact;
  lidar_ideal_class?: Artifact;
  lidar_range_preview?: Artifact;
  lidar_cloud_preview?: Artifact;
  lidar_topdown_preview?: Artifact;
  metadata: Artifact;
}
export interface CaptureJobError {
  code: "worker_crash" | "worker_timeout" | "worker_context_lost" | "worker_interrupted" | "worker_error";
  message: string;
}
export interface ObservationBundle {
  schema_version: "lab.v1";
  kind: "ObservationBundle";
  capture_id: Id;
  sequence_id: Id;
  rig: RigSpec;
  rgb: RgbObservation;
  ir: IrObservation;
  lidar: LidarObservation;
}
export interface Unavailable {
  status: "unavailable";
  reason: "not_implemented" | "disabled" | "hardware_failure";
  message: string;
}
export interface RgbData {
  image: ArrayArtifact & {
    dtype?: "uint8";
    units?: "1";
    frame?: "image-top-left";
    /**
     * @minItems 3
     * @maxItems 3
     */
    shape?: [number, number, 3];
    [k: string]: unknown;
  };
  validity_mask: ArrayArtifact & {
    dtype?: "bool";
    units?: "1";
    frame?: "image-top-left";
    /**
     * @minItems 2
     * @maxItems 2
     */
    shape?: [number, number];
    [k: string]: unknown;
  };
  transfer_function: "srgb";
  exposure_s: number;
}
export interface ArrayArtifact {
  artifact: Artifact;
  dtype: "uint8" | "uint16" | "uint32" | "float32" | "float64" | "bool";
  /**
   * @minItems 1
   * @maxItems 4
   */
  shape: [number] | [number, number] | [number, number, number] | [number, number, number, number];
  units: "1" | "pixel" | "m" | "s" | "K" | "W/m2/sr";
  frame: "image-top-left" | "optical-right-down-forward" | "lidar-forward-left-up" | "east-up-south";
}
export interface IrData {
  radiance: ArrayArtifact & {
    dtype?: "float32";
    units?: "W/m2/sr";
    frame?: "image-top-left";
    /**
     * @minItems 2
     * @maxItems 2
     */
    shape?: [number, number];
    [k: string]: unknown;
  };
  validity_mask: ArrayArtifact & {
    dtype?: "bool";
    units?: "1";
    frame?: "image-top-left";
    /**
     * @minItems 2
     * @maxItems 2
     */
    shape?: [number, number];
    [k: string]: unknown;
  };
  saturation_mask: ArrayArtifact & {
    dtype?: "bool";
    units?: "1";
    frame?: "image-top-left";
    /**
     * @minItems 2
     * @maxItems 2
     */
    shape?: [number, number];
    [k: string]: unknown;
  };
  /**
   * @minItems 2
   * @maxItems 2
   */
  band_um: [number, number];
  response_version: Version;
}
export interface LidarData {
  xyz: ArrayArtifact & {
    dtype?: "float32";
    units?: "m";
    frame?: "lidar-forward-left-up";
    /**
     * @minItems 2
     * @maxItems 2
     */
    shape?: [number, 3];
    [k: string]: unknown;
  };
  intensity: ArrayArtifact & {
    dtype?: "float32";
    units?: "1";
    frame?: "lidar-forward-left-up";
    /**
     * @minItems 1
     * @maxItems 1
     */
    shape?: [number];
    [k: string]: unknown;
  };
  beam_id: ArrayArtifact & {
    dtype?: "uint32";
    units?: "1";
    frame?: "lidar-forward-left-up";
    /**
     * @minItems 1
     * @maxItems 1
     */
    shape?: [number];
    [k: string]: unknown;
  };
  time_offset: ArrayArtifact & {
    dtype?: "float32";
    units?: "s";
    frame?: "lidar-forward-left-up";
    /**
     * @minItems 1
     * @maxItems 1
     */
    shape?: [number];
    [k: string]: unknown;
  };
  validity: ArrayArtifact & {
    dtype?: "bool";
    units?: "1";
    frame?: "lidar-forward-left-up";
    /**
     * @minItems 1
     * @maxItems 1
     */
    shape?: [number];
    [k: string]: unknown;
  };
  beam_table: ArrayArtifact & {
    dtype?: "uint8";
    units?: "1";
    frame?: "lidar-forward-left-up";
    /**
     * @minItems 1
     * @maxItems 1
     */
    shape?: [number];
    [k: string]: unknown;
  };
}
export interface AnnotationBundle {
  schema_version: "lab.v1";
  kind: "AnnotationBundle";
  capture_id: Id;
  class_map_version: Version;
  visibility_policy_version: Version;
  /**
   * @minItems 0
   * @maxItems 100000
   */
  objects: ObjectAnnotation[];
}
export interface ObjectAnnotation {
  instance_id: Id;
  class_id: number;
  box_3d: Box3;
  rgb: VisibleCamera;
  ir: VisibleCamera;
  lidar_ideal_hits: number;
  lidar_surface_hits: number;
  eligible: boolean;
  ignore_reason: ("out_of_frustum" | "fully_occluded" | "small_fragment") | null;
}
export interface VisibleCamera {
  mask: ArrayArtifact;
  visible_box_xyxy: [number, number, number, number] | null;
  visible_pixels: number;
  isolated_projected_pixels: number;
  visible_fraction: number | null;
  truncated: boolean;
}
export interface TruthBundle {
  schema_version: "lab.v1";
  kind: "TruthBundle";
  capture_id: Id;
  world: WorldSpec;
  actual_rig: RigSpec;
  environment: EnvironmentSpec;
  /**
   * @minItems 0
   * @maxItems 100000
   */
  objects: ObjectTruth[];
  /**
   * @minItems 0
   * @maxItems 100
   */
  clean_intermediates: Artifact[];
  /**
   * @minItems 0
   * @maxItems 100
   */
  corruption_masks: ArrayArtifact[];
}
export interface ObjectTruth {
  instance: Instance;
  velocity_m_per_s: Vec3;
  /**
   * @minItems 0
   * @maxItems 10000
   */
  surface_temperatures_k: {
    part_id: Id;
    temperature_k: number;
  }[];
}
export interface DatasetManifest {
  schema_version: "lab.v1";
  kind: "DatasetManifest";
  dataset_id: Id;
  created_utc: string;
  provenance: Provenance;
  /**
   * @minItems 1
   * @maxItems 65535
   */
  class_map: [
    {
      id: number;
      name: string;
    },
    ...{
      id: number;
      name: string;
    }[]
  ];
  class_map_version: Version;
  /**
   * @minItems 1
   * @maxItems 1000000
   */
  captures: [CaptureEntry, ...CaptureEntry[]];
  /**
   * @minItems 0
   * @maxItems 1000000
   */
  files: ArrayArtifact[];
  counts: {
    train: number;
    validation: number;
    test: number;
  };
}
export interface Provenance {
  source_revision: string;
  world_sha256: Hash;
  /**
   * @minItems 0
   * @maxItems 100000
   */
  asset_hashes: Hash[];
  config_sha256: Hash;
  sensor_version: Version;
  generator_version: Version;
  toolchain: string;
  seed: number;
}
export interface CaptureEntry {
  capture_id: Id;
  sequence_id: Id;
  group_id: Id;
  split: "train" | "validation" | "test";
  observation: Artifact;
  annotations: Artifact;
  truth: Artifact | null;
  /**
   * @minItems 1
   * @maxItems 1000
   */
  files?: [Artifact, ...Artifact[]];
}
export interface PredictionBundle {
  schema_version: "lab.v1";
  kind: "PredictionBundle";
  capture_id: Id;
  checkpoint_id: Id;
  checkpoint_sha256: Hash;
  latency_ms: number;
  /**
   * @minItems 0
   * @maxItems 10000
   */
  detections: Detection[];
  state: Artifact | null;
}
export interface Detection {
  prediction_id: Id;
  class_id: number;
  box_3d: Box3;
  score: number;
  /**
   * Null when a baseline does not estimate position variance.
   */
  position_variance_m2: [number, number, number] | null;
  observation_supported: boolean;
  routing: [number, number, number, number, number, number, number, number] | null;
}
export interface Health {
  schema_version: "lab.v1";
  kind: "Health";
  status: "ok";
  service: "yulab-backend";
  service_version: "0.1.0";
}
export interface Capabilities {
  schema_version: "lab.v1";
  kind: "Capabilities";
  service_version: "0.1.0";
  contracts_version: "lab.v1";
  capture_renderer: string | null;
  device: string | null;
  sensors: {
    rgb: Capability;
    ir: Capability;
    lidar: Capability;
  };
  services: {
    worlds: Capability;
    capture: Capability;
    datasets: Capability;
    training: Capability;
    inference: Capability;
  };
  /**
   * @minItems 0
   * @maxItems 1000
   */
  checkpoints: Id[];
}
export interface ApiError {
  schema_version: "lab.v1";
  kind: "ApiError";
  code: "not_found" | "method_not_allowed" | "validation_error" | "internal_error";
  message: string;
  request_id: Id;
  job_id: Id | null;
  /**
   * @minItems 0
   * @maxItems 100
   */
  details: {
    path: string;
    message: string;
  }[];
}
