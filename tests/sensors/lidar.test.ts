import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { cameraPoseToRig, projectWorldPoint } from "../../packages/sensors/src/index.ts";
import { beamFor, buildLidarScene, scanLidar } from "../../packages/sensors/src/lidar.ts";

function rig(rows = 1, columns = 1) {
  const value = cameraPoseToRig({
    rigId: "lidar-fixture", position: [0, 0, 0], quaternion: [0, 0, 0, 1],
    width: 640, height: 384, verticalFovRadians: 0.7,
  });
  const sensor = value.sensors.find((item) => item.modality === "lidar")!;
  sensor.available = true;
  sensor.lidar!.rows = rows;
  sensor.lidar!.columns = columns;
  sensor.lidar!.horizontal_fov_rad = columns === 1 ? 0.01 : 0.8;
  sensor.lidar!.vertical_fov_rad = rows === 1 ? 0.01 : 0.4;
  sensor.max_range_m = 30;
  sensor.scan_duration_s = 0.1;
  return value;
}

function box(scene: THREE.Scene, name: string, x: number, z: number, width = 2) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, 4, 0.1), new THREE.MeshBasicMaterial());
  mesh.name = name;
  mesh.position.set(x, 0, z);
  scene.add(mesh);
  return mesh;
}

test("first opaque wall wins; receiver dropout never exposes a hidden object", () => {
  const scene = new THREE.Scene();
  box(scene, "target", 0, -10);
  const wall = box(scene, "wall", 0, -5);
  const geometry = buildLidarScene(scene);
  const first = scanLidar(geometry, rig(), 7, { dropout_probability: 1 });
  assert.equal(first.ideal_hits[0]?.object_name, "wall");
  assert.equal(first.points.length, 0);
  assert.equal(first.beam_status[0], 2);
  geometry.dispose();
  scene.remove(wall);
  const open = buildLidarScene(scene);
  assert.equal(scanLidar(open, rig(), 7, { dropout_probability: 0 }).ideal_hits[0]?.object_name, "target");
  open.dispose();
});

test("partial occlusion, opening, range limits and empty scans preserve beam identities", () => {
  const scene = new THREE.Scene();
  box(scene, "target", 0, -10, 8);
  box(scene, "left-pier", -1.8, -5, 0.4);
  box(scene, "right-pier", 1.8, -5, 0.4);
  const value = rig(1, 9);
  const geometry = buildLidarScene(scene);
  const result = scanLidar(geometry, value, 0, { dropout_probability: 0, range_sigma_m: 0, intensity_sigma: 0 });
  assert.equal(result.beam_status.length, 9);
  assert.ok(result.ideal_hits.some((hit) => hit?.object_name === "target"));
  assert.ok(result.ideal_hits.some((hit) => hit?.object_name?.includes("pier")));
  assert.equal(result.points.length, result.beam_status.filter((status) => status === 1).length);
  assert.equal(result.points[0].time_offset_s, beamFor(value, 0, result.points[0].beam_id).time_offset_s);
  geometry.dispose();
  const empty = buildLidarScene(new THREE.Scene());
  assert.deepEqual(scanLidar(empty, value, 0).points, []);
  empty.dispose();
  const tooFar = rig();
  tooFar.sensors[2].max_range_m = 4;
  const targetOnly = buildLidarScene(scene);
  assert.equal(scanLidar(targetOnly, tooFar, 0).beam_status[0], 0);
  targetOnly.dispose();
});

test("accelerated first intersection matches independent brute force and rig projection", () => {
  const scene = new THREE.Scene();
  box(scene, "chunk:-1", -1, -6);
  box(scene, "chunk:0", 1, -7);
  const value = rig(3, 11);
  const geometry = buildLidarScene(scene);
  scene.updateMatrixWorld(true);
  const meshes = scene.children.filter((child): child is THREE.Mesh => child instanceof THREE.Mesh);
  for (let row = 0; row < 3; row++) for (let column = 0; column < 11; column++) {
    const beam = beamFor(value, row, column);
    const brute = new THREE.Raycaster(new THREE.Vector3(...beam.origin), new THREE.Vector3(...beam.direction), 0.1, 30)
      .intersectObjects(meshes, false)[0];
    const accelerated = geometry.first(beam.origin, beam.direction, 0.1, 30);
    assert.equal(accelerated?.object_name ?? null, brute?.object.name ?? null);
    if (brute && accelerated) assert.ok(Math.abs(accelerated.range_m - brute.distance) < 0.001);
  }
  const center = beamFor(value, 1, 5);
  const target = [center.origin[0] + 10 * center.direction[0], center.origin[1] + 10 * center.direction[1], center.origin[2] + 10 * center.direction[2]] as [number, number, number];
  const projected = projectWorldPoint(value, "rgb", target);
  assert.ok(Math.abs(projected.u - 320) < 0.5);
  assert.ok(Math.abs(projected.v - 192) < 0.5);
  geometry.dispose();
});
