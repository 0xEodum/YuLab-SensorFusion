import * as THREE from "three";
import type { RigSpec } from "@yulab/contracts";

type SensorRig = RigSpec["sensors"][number];
type Camera = NonNullable<SensorRig["camera"]>;
type Transform = RigSpec["T_world_from_rig"];
type Vec3 = [number, number, number];

export const SENSOR_PACKAGE_VERSION = "sensor-capture.v1";
export const REFERENCE_PASS_VERSION = "reference-pass.v1";
export const MAX_INSTANCE_ID = 0xff_ff_ff;

type CameraModality = "rgb" | "ir";
type CameraPoseInput = {
  rigId: string;
  position: Vec3;
  quaternion: [number, number, number, number];
  width: number;
  height: number;
  verticalFovRadians: number;
};

const OPTICAL_TO_THREE = new THREE.Matrix4().makeScale(1, -1, -1);

function transform(values: readonly number[]): Transform {
  if (values.length !== 16 || !values.every(Number.isFinite))
    throw new Error("Transform must contain 16 finite row-major values");
  return [...values] as Transform;
}

function matrix(values: readonly number[]) {
  return new THREE.Matrix4().set(
    values[0], values[1], values[2], values[3],
    values[4], values[5], values[6], values[7],
    values[8], values[9], values[10], values[11],
    values[12], values[13], values[14], values[15],
  );
}

function rowMajor(value: THREE.Matrix4): Transform {
  const e = value.elements;
  return transform([
    e[0], e[4], e[8], e[12],
    e[1], e[5], e[9], e[13],
    e[2], e[6], e[10], e[14],
    e[3], e[7], e[11], e[15],
  ]);
}

function assertRigid(name: string, values: readonly number[]) {
  if (values.length !== 16 || !values.every(Number.isFinite))
    throw new Error(`${name} must be a finite rigid transform`);
  const m = matrix(values), e = m.elements;
  if (
    Math.abs(e[3]) > 1e-9 || Math.abs(e[7]) > 1e-9 ||
    Math.abs(e[11]) > 1e-9 || Math.abs(e[15] - 1) > 1e-9
  ) throw new Error(`${name} must be a rigid affine transform`);
  const x = new THREE.Vector3(e[0], e[1], e[2]);
  const y = new THREE.Vector3(e[4], e[5], e[6]);
  const z = new THREE.Vector3(e[8], e[9], e[10]);
  if (
    Math.abs(x.length() - 1) > 1e-6 ||
    Math.abs(y.length() - 1) > 1e-6 ||
    Math.abs(z.length() - 1) > 1e-6 ||
    Math.abs(x.dot(y)) > 1e-6 ||
    Math.abs(x.dot(z)) > 1e-6 ||
    Math.abs(y.dot(z)) > 1e-6
  ) throw new Error(`${name} rotation must be rigid and orthonormal`);
  if (m.determinant() < 0.999999)
    throw new Error(`${name} rotation must be right-handed`);
}

export function validateRigGeometry(rig: RigSpec) {
  assertRigid("T_world_from_rig", rig.T_world_from_rig);
  const ids = new Set<string>();
  const modalities = new Set<string>();
  for (const sensor of rig.sensors) {
    if (ids.has(sensor.sensor_id)) throw new Error("Duplicate sensor ID");
    if (modalities.has(sensor.modality)) throw new Error("Duplicate sensor modality");
    ids.add(sensor.sensor_id);
    modalities.add(sensor.modality);
    assertRigid(`${sensor.sensor_id}.T_rig_from_sensor`, sensor.T_rig_from_sensor);
    if (sensor.camera) {
      const c = sensor.camera;
      if (
        !Number.isInteger(c.width_px) || !Number.isInteger(c.height_px) ||
        c.width_px < 1 || c.height_px < 1 ||
        ![c.fx_px, c.fy_px, c.cx_px, c.cy_px].every(Number.isFinite) ||
        c.fx_px <= 0 || c.fy_px <= 0
      ) throw new Error(`${sensor.sensor_id} has invalid camera intrinsics`);
    }
  }
  for (const modality of ["rgb", "ir", "lidar"])
    if (!modalities.has(modality)) throw new Error(`Missing ${modality} sensor`);
}

function cameraDefinition(
  modality: CameraModality,
  camera: Camera,
  baselineM: number,
): SensorRig {
  return {
    sensor_id: `${modality}-1`,
    modality,
    available: true,
    T_rig_from_sensor: transform([
      1, 0, 0, baselineM,
      0, -1, 0, 0,
      0, 0, -1, 0,
      0, 0, 0, 1,
    ]),
    timestamp_offset_s: 0,
    exposure_s: 0.01,
    scan_duration_s: 0,
    min_range_m: 0.1,
    max_range_m: 250,
    camera: { ...camera },
    lidar: null,
    sensor_model_version: `${modality}.v1`,
  };
}

export function cameraPoseToRig(input: CameraPoseInput): RigSpec {
  if (!input.rigId.trim() || input.rigId.length > 128)
    throw new Error("Rig ID is required");
  if (
    !Number.isInteger(input.width) || !Number.isInteger(input.height) ||
    input.width < 1 || input.height < 1 ||
    !Number.isFinite(input.verticalFovRadians) ||
    input.verticalFovRadians <= 0 || input.verticalFovRadians >= Math.PI
  ) throw new Error("Capture viewport and field of view are invalid");
  const q = new THREE.Quaternion(...input.quaternion);
  if (Math.abs(q.length() - 1) > 1e-6)
    throw new Error("Camera quaternion must be normalized");
  const pose = new THREE.Matrix4().compose(
    new THREE.Vector3(...input.position), q, new THREE.Vector3(1, 1, 1),
  );
  const focal = input.height / (2 * Math.tan(input.verticalFovRadians / 2));
  const camera: Camera = {
    frame: "optical-right-down-forward",
    width_px: input.width,
    height_px: input.height,
    fx_px: focal,
    fy_px: focal,
    cx_px: input.width / 2,
    cy_px: input.height / 2,
    distortion: "ideal-pinhole",
  };
  const rig: RigSpec = {
    schema_version: "lab.v1",
    kind: "RigSpec",
    rig_id: input.rigId,
    calibration_version: "cal.v1",
    T_world_from_rig: rowMajor(pose),
    sensors: [
      cameraDefinition("rgb", camera, 0),
      cameraDefinition("ir", camera, 0.35),
      {
        sensor_id: "lidar-1", modality: "lidar", available: false,
        T_rig_from_sensor: transform([
          0, 0, -1, 0,
          -1, 0, 0, 0,
          0, 1, 0, 0,
          0, 0, 0, 1,
        ]),
        timestamp_offset_s: 0, exposure_s: 0, scan_duration_s: 0,
        min_range_m: 0.1, max_range_m: 250, camera: null,
        lidar: {
          frame: "lidar-forward-left-up", rows: 64, columns: 512,
          horizontal_fov_rad: 1.2, vertical_fov_rad: 0.6,
          return_policy: "single-first-opaque",
        },
        sensor_model_version: "lidar.v1",
      },
    ],
    timing_profile: "synchronized-static",
  };
  validateRigGeometry(rig);
  return rig;
}

function cameraSensor(rig: RigSpec, modality: CameraModality) {
  validateRigGeometry(rig);
  const sensor = rig.sensors.find((item) => item.modality === modality);
  if (!sensor?.available || !sensor.camera)
    throw new Error(`${modality} camera is unavailable`);
  return sensor;
}

export function captureCamera(rig: RigSpec, modality: CameraModality) {
  const sensor = cameraSensor(rig, modality);
  const worldFromSensor = matrix(rig.T_world_from_rig).multiply(
    matrix(sensor.T_rig_from_sensor),
  );
  return {
    sensor_id: sensor.sensor_id,
    camera: { ...sensor.camera! },
    min_range_m: sensor.min_range_m,
    max_range_m: sensor.max_range_m,
    T_world_from_sensor: rowMajor(worldFromSensor),
    T_world_from_camera: rowMajor(worldFromSensor.multiply(OPTICAL_TO_THREE)),
  };
}

export function fixedCaptureViewport(rig: RigSpec, modality: CameraModality) {
  const camera = cameraSensor(rig, modality).camera!;
  return { width: camera.width_px, height: camera.height_px };
}

export function projectWorldPoint(
  rig: RigSpec,
  modality: CameraModality,
  point: Vec3,
) {
  const sensor = cameraSensor(rig, modality);
  const sensorFromWorld = matrix(rig.T_world_from_rig)
    .multiply(matrix(sensor.T_rig_from_sensor))
    .invert();
  const p = new THREE.Vector3(...point).applyMatrix4(sensorFromWorld);
  const c = sensor.camera!;
  const u = c.fx_px * p.x / p.z + c.cx_px;
  const v = c.fy_px * p.y / p.z + c.cy_px;
  return {
    u,
    v,
    depth_m: p.z,
    in_frame:
      p.z >= sensor.min_range_m && p.z <= sensor.max_range_m &&
      u >= 0 && u < c.width_px && v >= 0 && v < c.height_px,
  };
}

export function worldRayForPixel(
  rig: RigSpec,
  modality: "rgb" | "ir",
  u: number,
  v: number,
) {
  if (![u, v].every(Number.isFinite)) throw new Error("Pixel coordinates must be finite");
  const sensor = cameraSensor(rig, modality), c = sensor.camera!;
  const worldFromSensor = matrix(rig.T_world_from_rig).multiply(matrix(sensor.T_rig_from_sensor));
  const origin = new THREE.Vector3().setFromMatrixPosition(worldFromSensor);
  const direction = new THREE.Vector3(
    (u - c.cx_px) / c.fx_px,
    (v - c.cy_px) / c.fy_px,
    1,
  ).normalize().transformDirection(worldFromSensor);
  return {
    origin: origin.toArray() as Vec3,
    direction: direction.toArray() as Vec3,
  };
}

export function encodeInstanceId(id: number): [number, number, number] {
  if (!Number.isInteger(id) || id < 0 || id > MAX_INSTANCE_ID)
    throw new Error(`Instance ID must be an integer in 0..${MAX_INSTANCE_ID}`);
  return [id & 255, (id >>> 8) & 255, (id >>> 16) & 255];
}

export function decodeInstanceId(rgb: ArrayLike<number>) {
  if (rgb.length < 3 || ![rgb[0], rgb[1], rgb[2]].every((v) => Number.isInteger(v) && v >= 0 && v <= 255))
    throw new Error("Instance RGB must contain three bytes");
  return rgb[0] | (rgb[1] << 8) | (rgb[2] << 16);
}

export function flipRows<T extends Uint8Array | Uint32Array | Float32Array>(
  source: T,
  width: number,
  height: number,
  channels = 1,
): T {
  if (
    !Number.isInteger(width) || !Number.isInteger(height) ||
    !Number.isInteger(channels) || width < 1 || height < 1 || channels < 1 ||
    source.length !== width * height * channels
  ) throw new Error("Invalid raster dimensions");
  const output = new (source.constructor as { new(length: number): T })(source.length);
  const stride = width * channels;
  for (let y = 0; y < height; y++)
    output.set(source.subarray(y * stride, (y + 1) * stride), (height - 1 - y) * stride);
  return output;
}

export function shouldCaptureObject(object: {
  visible: boolean;
  userData?: Record<string, unknown>;
}) {
  if (!object.visible || object.userData?.sensorExcluded === true) return false;
  return !new Set(["helper", "grid", "decorative-shadow-floor", "ui-overlay"])
    .has(String(object.userData?.renderRole ?? ""));
}

export { renderReferencePasses, rendererCapabilities } from "./capture.ts";
export type { ReferenceCapture } from "./capture.ts";
