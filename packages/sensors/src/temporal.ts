import * as THREE from "three";
import type { RigSpec, TemporalCapture } from "@yulab/contracts";
import { validatePayload } from "../../contracts/src/validate.ts";
import { validateRigGeometry } from "./index.ts";

type Modality = RigSpec["sensors"][number]["modality"];
type Transform = RigSpec["T_world_from_rig"];
const matrix = (v: readonly number[]) => new THREE.Matrix4().set(...v as Parameters<THREE.Matrix4["set"]>);
const rowMajor = (m: THREE.Matrix4) => m.clone().transpose().toArray() as Transform;

/** Nominal rig is anchored at captureTime; drift is anchored at reference_time_s.
 * Translations use world/rig axes respectively. Yaw rotates orientation around
 * each platform/sensor origin, without rotating the translated origin. */
export function temporalSampler(nominal: RigSpec, state: TemporalCapture, captureTime: number) {
  validatePayload("TemporalCapture", state);
  validateRigGeometry(nominal);
  if (!Number.isFinite(captureTime) || captureTime < 0) throw new Error("Invalid capture time");
  const drifts = new Map(state.sensor_drift.map(d => [d.modality, structuredClone(d)]));
  if (drifts.size !== state.sensor_drift.length) throw new Error("Duplicate sensor drift modality");
  // Snapshot once: changing the caller's rig or motion cannot mutate an in-flight scan.
  const base = structuredClone(nominal), motion = structuredClone(state);
  const check = (offset: number) => {
    if (!Number.isFinite(offset) || captureTime + offset < 0) throw new Error("Invalid sample time");
  };
  const advance = (values: readonly number[], velocity: readonly number[], dt: number, yaw: number) => {
    const m = matrix(values), position = new THREE.Vector3().setFromMatrixPosition(m);
    m.setPosition(0, 0, 0).premultiply(new THREE.Matrix4().makeRotationY(yaw));
    m.setPosition(position.addScaledVector(new THREE.Vector3(...velocity), dt));
    return m;
  };
  const world = (offset: number) => advance(base.T_world_from_rig, motion.velocity_world_m_per_s,
    offset, motion.yaw_rate_rad_per_s * offset);
  const extrinsic = (sensor: RigSpec["sensors"][number], offset: number) => {
    const drift = drifts.get(sensor.modality);
    if (!drift) return matrix(sensor.T_rig_from_sensor);
    const dt = captureTime + offset - motion.reference_time_s;
    const m = advance(sensor.T_rig_from_sensor, drift.translation_rate_rig_m_per_s, dt,
      drift.yaw_rad + drift.yaw_rate_rad_per_s * dt);
    m.elements[12] += drift.translation_rig_m[0];
    m.elements[13] += drift.translation_rig_m[1];
    m.elements[14] += drift.translation_rig_m[2];
    return m;
  };
  return {
    rigAt(offset: number): RigSpec {
      check(offset);
      const rig = structuredClone(base);
      rig.T_world_from_rig = rowMajor(world(offset));
      for (const sensor of rig.sensors) sensor.T_rig_from_sensor = rowMajor(extrinsic(sensor, offset));
      return rig;
    },
    sensorTransform(modality: Modality, offset: number): THREE.Matrix4 {
      check(offset);
      const sensor = base.sensors.find(s => s.modality === modality);
      if (!sensor) throw new Error("Unknown sensor modality");
      return world(offset).multiply(extrinsic(sensor, offset));
    },
  };
}
