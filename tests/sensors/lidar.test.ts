import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import type { AssetRecord } from "../../packages/contracts/src/generated.ts";
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
  box(scene, "left-pier", -1.55, -5, 0.7);
  box(scene, "right-pier", 1.55, -5, 0.7);
  const value = rig(1, 9);
  const geometry = buildLidarScene(scene);
  const result = scanLidar(geometry, value, 0, { dropout_probability: 0, range_sigma_m: 0, intensity_sigma: 0 });
  assert.equal(result.beam_status.length, 9);
  assert.ok(beamFor(value, 0, 0).direction_sensor[1] > 0);
  assert.ok(beamFor(value, 0, 8).direction_sensor[1] < 0);
  assert.ok(result.ideal_hits.some((hit) => hit?.object_name === "target"));
  assert.ok(result.ideal_hits.some((hit) => hit?.object_name?.includes("pier")));
  assert.equal(result.points.length, result.beam_status.filter((status) => status === 1).length);
  assert.equal(result.beam_status.includes(2), false);
  assert.ok(result.points.every((point) => point.xyz_sensor.every(Number.isFinite) && Number.isFinite(point.intensity)));
  for (let seed = 0; seed < 30; seed++) {
    const sampled = scanLidar(geometry, value, seed);
    assert.equal(sampled.beam_status.includes(2), false);
    assert.ok(sampled.points.every((point) => point.xyz_sensor.every(Number.isFinite) && Number.isFinite(point.intensity)));
  }
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
  assert.equal(geometry.first([-0.001, 0, 0], [0, 0, -1], 0.1, 30)?.object_name, "chunk:-1");
  assert.equal(geometry.first([0.001, 0, 0], [0, 0, -1], 0.1, 30)?.object_name, "chunk:0");
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

test("thin faces are two-sided; inside solids return the exit face", () => {
  const scene = new THREE.Scene();
  const thin = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial());
  thin.name = "thin";
  thin.position.z = -5;
  scene.add(thin);
  const index = buildLidarScene(scene);
  assert.ok(Math.abs(index.first([0, 0, 0], [0, 0, -1], 0.1, 30)!.range_m - 5) < 1e-6);
  assert.ok(Math.abs(index.first([0, 0, -10], [0, 0, 1], 0.1, 30)!.range_m - 5) < 1e-6);
  index.dispose();
  scene.remove(thin);
  const solid = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshBasicMaterial());
  solid.name = "solid";
  scene.add(solid);
  const inside = buildLidarScene(scene);
  assert.ok(Math.abs(inside.first([0, 0, 0], [0, 0, -1], 0.1, 30)!.range_m - 1) < 1e-6);
  assert.equal(inside.first([0, 0, 0], [0, 0, -1], 1.1, 30), null);
  inside.dispose();
});

test("coplanar ties choose the first scene mesh consistently", () => {
  const scene = new THREE.Scene();
  box(scene, "first", 0, -5);
  box(scene, "second", 0, -5);
  const index = buildLidarScene(scene);
  for (let i = 0; i < 5; i++)
    assert.equal(index.first([0, 0, 0], [0, 0, -1], 0.1, 30)?.object_name, "first");
  index.dispose();
});

test("arch opening admits a central beam while its lintel occludes elevated beams", () => {
  const scene = new THREE.Scene();
  const target = new THREE.Mesh(new THREE.BoxGeometry(8, 10, 0.1), new THREE.MeshBasicMaterial());
  target.name = "target";
  target.position.z = -10;
  scene.add(target);
  const lintel = new THREE.Mesh(new THREE.BoxGeometry(3, 1, 0.2), new THREE.MeshBasicMaterial());
  lintel.name = "lintel";
  lintel.position.set(0, 2, -5);
  scene.add(lintel);
  const index = buildLidarScene(scene);
  assert.equal(index.first([0, 0, 0], [0, 0, -1], 0.1, 30)?.object_name, "target");
  const elevated = new THREE.Vector3(0, Math.sin(0.4), -Math.cos(0.4));
  assert.equal(index.first([0, 0, 0], elevated.toArray() as [number, number, number], 0.1, 30)?.object_name, "lintel");
  index.dispose();
  scene.remove(lintel);
  const open = buildLidarScene(scene);
  assert.equal(open.first([0, 0, 0], elevated.toArray() as [number, number, number], 0.1, 30)?.object_name, "target");
  open.dispose();
});

test("grazing thin face stays visible with a weak synthetic response", () => {
  const scene = new THREE.Scene();
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(10, 10), new THREE.MeshBasicMaterial());
  plane.name = "grazing";
  plane.rotation.y = Math.PI / 2 - 0.01;
  plane.position.z = -5;
  scene.add(plane);
  const index = buildLidarScene(scene);
  const result = scanLidar(index, rig(), 2, { range_sigma_m: 0, intensity_sigma: 0 });
  assert.ok(Math.abs(result.ideal_hits[0]!.range_m - 5) < 0.001);
  assert.equal(result.points.length, 1);
  assert.ok(result.points[0].intensity < 0.02);
  index.dispose();
});

test("catalog LiDAR opacity excludes declared non-opaque asset surfaces", () => {
  const scene = new THREE.Scene();
  const asset = new THREE.Group();
  asset.userData = { instance_id: "asset-1", asset_id: "fixture" };
  const surface = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial());
  surface.name = "surface";
  surface.position.z = -5;
  surface.userData.source_parts = ["part-1"];
  asset.add(surface);
  scene.add(asset);
  const record = {
    asset_id: "fixture", parts: [{ mesh_node: "part-1", material_id: "mat-1" }],
    materials: [{ id: "mat-1", opaque_lidar: false }],
  } as unknown as AssetRecord;
  const excluded = buildLidarScene(scene, [record]);
  assert.equal(excluded.mesh_count, 0);
  assert.equal(excluded.first([0, 0, 0], [0, 0, -1], 0.1, 30), null);
  excluded.dispose();
  record.materials[0].opaque_lidar = true;
  const included = buildLidarScene(scene, [record]);
  assert.equal(included.first([0, 0, 0], [0, 0, -1], 0.1, 30)?.instance_id, "asset-1");
  included.dispose();
});
