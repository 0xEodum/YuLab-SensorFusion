import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { readFileSync } from "node:fs";
import { cameraPoseToRig } from "../../packages/sensors/src/index.ts";
import { buildLidarScene, scanLidar } from "../../packages/sensors/src/lidar.ts";
import { objectMotionSampler, buildMovingLidarScene } from "../../packages/sensors/src/objectMotion.ts";
import type { WorldSpec, TemporalCapture } from "../../packages/contracts/src/generated.ts";

function fixture(velocity: [number, number, number] = [0, 0, -2], yaw = 0) {
  const world = JSON.parse(readFileSync(new URL("../../contracts/fixtures/WorldSpec.json", import.meta.url), "utf8")) as WorldSpec;
  world.instances[0].T_world_from_asset[11] = -10;
  const state: TemporalCapture = {schema_version: "lab.v1", kind: "TemporalCapture", profile: "rig-motion-drift.v1",
    reference_time_s: 0, velocity_world_m_per_s: [0, 0, 0], yaw_rate_rad_per_s: 0, sensor_drift: [],
    object_motion: [{instance_id: "aircraft-1", velocity_world_m_per_s: velocity, yaw_rate_rad_per_s: yaw}]};
  const scene = new THREE.Scene(), group = new THREE.Group();
  group.name = "aircraft-1"; group.position.z = -10;
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(100, 100, .1), new THREE.MeshBasicMaterial());
  group.add(mesh); scene.add(group); scene.updateMatrixWorld(true);
  const rig = cameraPoseToRig({rigId: "object-motion", position: [0, 0, 0], quaternion: [0, 0, 0, 1], width: 64, height: 48, verticalFovRadians: .7});
  rig.sensors[2].available = true; rig.sensors[2].lidar!.rows = 1; rig.sensors[2].lidar!.columns = 3;
  rig.sensors[2].lidar!.horizontal_fov_rad = .01; rig.sensors[2].scan_duration_s = 1;
  return {world, state, scene, group, rig};
}

test("moving wall is intersected at emission time, rather than frozen at scan start", () => {
  const {world, state, scene, rig} = fixture();
  const motion = objectMotionSampler(world, state, 0);
  const geometry = buildMovingLidarScene(scene, [], null, motion);
  const scan = scanLidar(geometry, rig, 0, {range_sigma_m: 0, intensity_sigma: 0});
  assert.equal(scan.points.length, 3);
  for (const p of scan.points) assert.ok(Math.abs(p.xyz_sensor[0] - (9.95 + 2 * p.time_offset_s)) < 1e-5);
  geometry.dispose();
});

test("rotation and translation match independent brute-force scene poses", () => {
  const {world, state, scene, group} = fixture([1, 0, -1], .2);
  const motion = objectMotionSampler(world, state, 2);
  motion.apply(scene, 0);
  const geometry = buildMovingLidarScene(scene, [], null, motion);
  for (const offset of [0, .1, .4, 1]) {
    const t = 2 + offset;
    group.position.set(t, 0, -10-t); group.rotation.y = .2*t;
    group.matrixAutoUpdate = true; scene.updateMatrixWorld(true);
    const brute = new THREE.Raycaster(new THREE.Vector3(0,0,0),new THREE.Vector3(0,0,-1), .1, 100).intersectObjects([group],true)[0];
    const hit = geometry.first([0,0,0],[0,0,-1],.1,100,offset);
    assert.equal(Boolean(hit),Boolean(brute));
    if (hit && brute) assert.ok(Math.abs(hit.range_m-brute.distance)<1e-5);
  }
  geometry.dispose();
});

test("zero object motion preserves exact static results; immutable reference and stable replay", () => {
  const {world,state,scene,rig} = fixture([0,0,0]);
  const before = structuredClone(world), motion=objectMotionSampler(world,state,3);
  motion.apply(scene,0);
  const moving=buildMovingLidarScene(scene,[],null,motion), original=buildLidarScene(scene);
  assert.deepEqual(scanLidar(moving,rig,3),scanLidar(original,rig,3));
  assert.deepEqual(world,before);
  assert.deepEqual(motion.worldAt(.2),objectMotionSampler(world,state,3).worldAt(.2));
  moving.dispose(); original.dispose();
});

test("unknown/duplicate trajectories fail; foreground static occluder still wins", () => {
  const {world,state,scene,rig} = fixture();
  const bad=structuredClone(state); bad.object_motion![0].instance_id="unknown";
  assert.throws(()=>objectMotionSampler(world,bad,0));
  const duplicate=structuredClone(state); duplicate.object_motion!.push(duplicate.object_motion![0]);
  assert.throws(()=>objectMotionSampler(world,duplicate,0));
  const wall=new THREE.Mesh(new THREE.BoxGeometry(100,100,.1),new THREE.MeshBasicMaterial());
  wall.position.z=-5; wall.name="opaque-static"; scene.add(wall);
  const geometry=buildMovingLidarScene(scene,[],null,objectMotionSampler(world,state,0));
  assert.ok(scanLidar(geometry,rig,0).ideal_hits.every(h=>h?.object_name==="opaque-static"));
  geometry.dispose();
});
