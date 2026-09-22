import test from "node:test";
import assert from "node:assert/strict";
import type { RigSpec } from "../../packages/contracts/src/generated.ts";
import {
  cameraPoseToRig,
  captureCamera,
  fixedCaptureViewport,
  projectWorldPoint,
  worldRayForPixel,
  validateRigGeometry,
} from "../../packages/sensors/src/index.ts";
import * as THREE from "three";

const identity = [
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
  0, 0, 0, 1,
] as const;
const opticalAt = (x: number) => [
  1, 0, 0, x,
  0, -1, 0, 0,
  0, 0, -1, 0,
  0, 0, 0, 1,
] as const;

function fixtureRig(): RigSpec {
  const camera = {
    frame: "optical-right-down-forward" as const,
    width_px: 640,
    height_px: 384,
    fx_px: 500,
    fy_px: 500,
    cx_px: 320,
    cy_px: 192,
    distortion: "ideal-pinhole" as const,
  };
  return {
    schema_version: "lab.v1",
    kind: "RigSpec",
    rig_id: "projection-fixture",
    calibration_version: "cal.v1",
    T_world_from_rig: [...identity],
    sensors: [
      {
        sensor_id: "rgb-1", modality: "rgb", available: true,
        T_rig_from_sensor: [...opticalAt(0)], timestamp_offset_s: 0,
        exposure_s: 0.01, scan_duration_s: 0, min_range_m: 0.1,
        max_range_m: 250, camera, lidar: null, sensor_model_version: "rgb.v1",
      },
      {
        sensor_id: "ir-1", modality: "ir", available: true,
        T_rig_from_sensor: [...opticalAt(0.5)], timestamp_offset_s: 0,
        exposure_s: 0.01, scan_duration_s: 0, min_range_m: 0.1,
        max_range_m: 250, camera, lidar: null, sensor_model_version: "ir.v1",
      },
      {
        sensor_id: "lidar-1", modality: "lidar", available: false,
        T_rig_from_sensor: [...identity], timestamp_offset_s: 0,
        exposure_s: 0, scan_duration_s: 0, min_range_m: 0.1,
        max_range_m: 250, camera: null,
        lidar: { frame: "lidar-forward-left-up", rows: 64, columns: 512,
          horizontal_fov_rad: 1.2, vertical_fov_rad: 0.6,
          return_policy: "single-first-opaque" },
        sensor_model_version: "lidar.v1",
      },
    ],
    timing_profile: "synchronized-static",
  };
}

test("known pinhole fixtures project within half a pixel and preserve parallax", () => {
  const rig = fixtureRig();
  validateRigGeometry(rig);
  assert.deepEqual(projectWorldPoint(rig, "rgb", [0, 0, -10]), {
    u: 320, v: 192, depth_m: 10, in_frame: true,
  });
  assert.deepEqual(projectWorldPoint(rig, "rgb", [1, -0.5, -10]), {
    u: 370, v: 217, depth_m: 10, in_frame: true,
  });
  const shifted = projectWorldPoint(rig, "ir", [0, 0, -10]);
  assert.equal(shifted.u, 295);
  assert.equal(shifted.depth_m, 10);
  assert.ok(Math.abs(shifted.u - 320) > 0.5);
});

test("a saved Three.js camera becomes an exact calibrated rig view", () => {
  const rig = cameraPoseToRig({
    rigId: "saved-rig",
    position: [12, 34, 56],
    quaternion: [0, 0, 0, 1],
    width: 640,
    height: 384,
    verticalFovRadians: 0.7330382858376184,
  });
  validateRigGeometry(rig);
  assert.deepEqual(captureCamera(rig, "rgb").T_world_from_camera, [
    1, 0, 0, 12,
    0, 1, 0, 34,
    0, 0, 1, 56,
    0, 0, 0, 1,
  ]);
  assert.deepEqual(fixedCaptureViewport(rig, "rgb"), { width: 640, height: 384 });
});

test("capture dimensions and pose come only from the saved rig", () => {
  const rig = fixtureRig();
  const before = captureCamera(rig, "rgb");
  for (const display of [[320, 200], [1920, 1080], [7, 9]]) {
    assert.deepEqual(fixedCaptureViewport(rig, "rgb"), { width: 640, height: 384 });
    assert.deepEqual(captureCamera(rig, "rgb"), before);
    assert.notDeepEqual(display, [640, 384]);
  }
});

test("non-rigid, reflected, duplicate and malformed rigs fail explicitly", () => {
  const rig = fixtureRig();
  rig.T_world_from_rig[0] = 2;
  assert.throws(() => validateRigGeometry(rig), /rigid/i);
  const duplicate = fixtureRig();
  duplicate.sensors[1].sensor_id = "rgb-1";
  assert.throws(() => validateRigGeometry(duplicate), /duplicate/i);
  const reflected = fixtureRig();
  reflected.T_world_from_rig[10] = -1;
  assert.throws(() => validateRigGeometry(reflected), /right-handed/i);
});

test("separate camera extrinsics change physical occlusion, not only pixel coordinates", () => {
  const rig = fixtureRig();
  const target = new THREE.Mesh(new THREE.SphereGeometry(0.3), new THREE.MeshBasicMaterial());
  target.position.set(0, 0, -10);
  target.updateMatrixWorld(true);
  const occluder = new THREE.Mesh(new THREE.BoxGeometry(0.2, 2, 0.2), new THREE.MeshBasicMaterial());
  occluder.position.set(0, 0, -5);
  occluder.updateMatrixWorld(true);
  const rgbPixel = projectWorldPoint(rig, "rgb", [0, 0, -10]);
  const irPixel = projectWorldPoint(rig, "ir", [0, 0, -10]);
  const first = (modality: "rgb" | "ir", u: number, v: number) => {
    const ray = worldRayForPixel(rig, modality, u, v);
    return new THREE.Raycaster(
      new THREE.Vector3(...ray.origin),
      new THREE.Vector3(...ray.direction),
    ).intersectObjects([occluder, target])[0]?.object;
  };
  assert.equal(first("rgb", rgbPixel.u, rgbPixel.v), occluder);
  assert.equal(first("ir", irPixel.u, irPixel.v), target);
});
