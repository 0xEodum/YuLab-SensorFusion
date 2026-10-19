import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { cameraPoseToRig, validateRigGeometry } from "../../packages/sensors/src/index.ts";
import { buildLidarScene, scanLidar } from "../../packages/sensors/src/lidar.ts";
import { temporalSampler } from "../../packages/sensors/src/temporal.ts";

const state = () => ({ schema_version: "lab.v1" as const, kind: "TemporalCapture" as const,
  profile: "rig-motion-drift.v1" as const, reference_time_s: 0,
  velocity_world_m_per_s: [0, 0, 0] as [number, number, number], yaw_rate_rad_per_s: 0,
  sensor_drift: [{ modality: "lidar" as const, translation_rig_m: [0, 0, 0] as [number, number, number],
    translation_rate_rig_m_per_s: [0, 0, 0] as [number, number, number], yaw_rad: 0, yaw_rate_rad_per_s: 0 }] });
function fixture() {
  const rig = cameraPoseToRig({rigId: "temporal-rig", position: [0, 0, 0],
    quaternion: [0, 0, 0, 1], width: 64, height: 48, verticalFovRadians: .7});
  const s = rig.sensors.find(s => s.modality === "lidar")!;
  s.available = true; s.lidar!.rows = 1; s.lidar!.columns = 3;
  s.lidar!.horizontal_fov_rad = .01; s.scan_duration_s = 1; s.max_range_m = 30;
  const scene = new THREE.Scene();
  const wall = new THREE.Mesh(new THREE.BoxGeometry(100, 100, .1), new THREE.MeshBasicMaterial());
  wall.position.z = -10; scene.add(wall);
  return {rig, geometry: buildLidarScene(scene)};
}

test("zero motion/drift preserves the exact static scan; nominal rig stays immutable", () => {
  const {rig, geometry} = fixture(), before = structuredClone(rig);
  const sampler = temporalSampler(rig, state(), 2);
  const response = {range_sigma_m: 0, intensity_sigma: 0};
  assert.deepEqual(scanLidar(geometry, rig, 7, {...response,
    pose_at: (t: number) => sampler.sensorTransform("lidar", t)}), scanLidar(geometry, rig, 7, response));
  assert.deepEqual(rig, before);
  assert.deepEqual(sampler.rigAt(0), rig);
  geometry.dispose();
});

test("moving platform uses each beam time and returns instantaneous sensor coordinates", () => {
  const {rig, geometry} = fixture(), motion = state();
  motion.velocity_world_m_per_s = [0, 0, -2];
  const sampler = temporalSampler(rig, motion, 5);
  const scan = scanLidar(geometry, rig, 0, {range_sigma_m: 0, intensity_sigma: 0,
    pose_at: (t: number) => sampler.sensorTransform("lidar", t)});
  assert.equal(scan.points.length, 3);
  for (const p of scan.points) {
    const forward = p.xyz_sensor[0];
    assert.ok(Math.abs(forward - (9.95 - 2 * p.time_offset_s)) < 1e-5);
    const world = new THREE.Vector3(...p.xyz_sensor).applyMatrix4(sampler.sensorTransform("lidar", p.time_offset_s));
    assert.ok(Math.abs(world.z + 9.95) < 1e-5);
  }
  // Pretending all returns came from scan-start pose yields exactly the traveled distance.
  assert.ok(Math.abs(scan.points[2].xyz_sensor[0] - 7.95) < 1e-5);
  geometry.dispose();
});

test("drift is evaluated at absolute sample time; rigid yaw preserves sensor origin", () => {
  const {rig, geometry} = fixture(), motion = state();
  motion.sensor_drift[0].translation_rig_m = [1, 0, 0];
  motion.sensor_drift[0].translation_rate_rig_m_per_s = [.5, 0, 0];
  motion.sensor_drift[0].yaw_rate_rad_per_s = .1;
  const before = structuredClone(rig), sampler = temporalSampler(rig, motion, 2);
  const actual = sampler.rigAt(1), sensor = actual.sensors[2];
  assert.ok(Math.abs(sensor.T_rig_from_sensor[3] - (rig.sensors[2].T_rig_from_sensor[3] + 2.5)) < 1e-9);
  validateRigGeometry(actual);
  assert.notDeepEqual(actual.sensors[2].T_rig_from_sensor, rig.sensors[2].T_rig_from_sensor);
  assert.deepEqual(rig, before);
  geometry.dispose();
});

test("sensor timestamp offset advances motion once; invalid transforms/times fail", () => {
  const {rig, geometry} = fixture(), motion = state();
  rig.sensors[2].timestamp_offset_s = .2; motion.velocity_world_m_per_s = [0, 0, -2];
  const sampler = temporalSampler(rig, motion, 0);
  const scan = scanLidar(geometry, rig, 0, {range_sigma_m: 0,
    pose_at: (t: number) => sampler.sensorTransform("lidar", t)});
  assert.ok(Math.abs(scan.points[0].xyz_sensor[0] - 9.55) < 1e-5);
  assert.throws(() => sampler.rigAt(NaN));
  assert.throws(() => temporalSampler(rig, {...motion, sensor_drift: [...motion.sensor_drift, ...motion.sensor_drift]}, 0));
  assert.throws(() => scanLidar(geometry, rig, 0, {pose_at: () => new THREE.Matrix4().makeScale(2, 1, 1)}));
  geometry.dispose();
});
