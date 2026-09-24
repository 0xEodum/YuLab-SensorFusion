import * as THREE from "three";
import { AssetLibrary, buildAerodromeScene, loadCatalog, type Catalog } from "@yulab/assets";
import { HARBOR_GENERATOR, AERODROME_GENERATOR } from "@yulab/world";
import { validatePayload } from "@yulab/contracts";
import type { CapturePlan, EnvironmentSpec, RigSpec, WorldSpec } from "@yulab/contracts";
import {
  createWorld,
  chunkPlacements,
  meshChunk,
  sensorChunks,
  type ChunkData,
} from "@yulab/world";
import {
  captureCamera,
  validateRigGeometry,
} from "@yulab/sensors";
import { beamFor, buildLidarScene, scanLidar } from "@yulab/sensors/lidar";
import { LIDAR_CLASS_TABLE } from "@yulab/sensors/lidarClass";
import { renderReferencePasses, renderThermalPass, rendererCapabilities } from "@yulab/sensors/capture";
import {
  advanceThermalState,
  decodeThermalState,
  encodeThermalState,
  initializeThermalState,
} from "@yulab/sensors/thermal";
import { weatherResponse } from "@yulab/sensors/weather";

type Request = {
  world: WorldSpec;
  rig: RigSpec;
  environment: EnvironmentSpec;
  plan: CapturePlan;
  _thermal_state_json?: string;
};

function bytesBase64(bytes: Uint8Array) {
  let binary = "";
  for (let start = 0; start < bytes.length; start += 0x8000)
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  return btoa(binary);
}

function dataUrlBase64(value: string) {
  const marker = ";base64,";
  const index = value.indexOf(marker);
  if (index < 0) throw new Error("Preview encoder did not return base64 PNG");
  return value.slice(index + marker.length);
}

function lidarPreviews(
  scan: ReturnType<typeof scanLidar>, rig: RigSpec, maxRange: number,
) {
  const range = document.createElement("canvas");
  range.width = scan.columns;
  range.height = scan.rows;
  const rangeContext = range.getContext("2d");
  if (!rangeContext) throw new Error("LiDAR range preview canvas unavailable");
  const pixels = rangeContext.createImageData(scan.columns, scan.rows);
  for (let i = 0; i < scan.beam_status.length; i++) {
    const offset = i * 4;
    const status = scan.beam_status[i];
    const value = status === 1
      ? Math.round(255 * (1 - Math.log1p(scan.ideal_hits[i]!.range_m) / Math.log1p(maxRange)))
      : 0;
    pixels.data[offset] = status === 2 ? 120 : status === 3 ? 240 : status === 4 ? 85 : Math.round(value * 0.38);
    pixels.data[offset + 1] = status === 2 ? 20 : status === 3 ? 225 : status === 4 ? 30 : Math.round(value * 0.78);
    pixels.data[offset + 2] = status === 2 ? 160 : status === 3 ? 70 : status === 4 ? 90 : value;
    pixels.data[offset + 3] = 255;
  }
  rangeContext.putImageData(pixels, 0, 0);
  const rgb = captureCamera(rig, "rgb");
  const toMatrix = (values: readonly number[]) => new THREE.Matrix4().set(
    ...values as Parameters<THREE.Matrix4["set"]>,
  );
  const worldFromLidar = toMatrix(rig.T_world_from_rig).multiply(
    toMatrix(rig.sensors.find((sensor) => sensor.modality === "lidar")!.T_rig_from_sensor),
  );
  const cameraFromWorld = toMatrix(rgb.T_world_from_sensor).invert();
  const lidarToCamera = cameraFromWorld.multiply(worldFromLidar);
  const cloud = document.createElement("canvas");
  cloud.width = rgb.camera.width_px;
  cloud.height = rgb.camera.height_px;
  const cloudContext = cloud.getContext("2d");
  if (!cloudContext) throw new Error("LiDAR camera-perspective preview canvas unavailable");
  const cameraPixels = cloudContext.createImageData(cloud.width, cloud.height);
  const cameraDepth = new Float32Array(cloud.width * cloud.height).fill(Infinity);
  const overhead = document.createElement("canvas");
  overhead.width = cloud.width;
  overhead.height = cloud.height;
  const overheadContext = overhead.getContext("2d");
  if (!overheadContext) throw new Error("LiDAR top-down preview canvas unavailable");
  const overheadPixels = overheadContext.createImageData(overhead.width, overhead.height);
  const overheadHeight = new Float32Array(overhead.width * overhead.height).fill(-Infinity);
  for (const data of [cameraPixels.data, overheadPixels.data]) {
    for (let i = 0; i < data.length; i += 4) {
      data[i] = 6; data[i + 1] = 18; data[i + 2] = 29; data[i + 3] = 255;
    }
  }
  const rgbBytes = LIDAR_CLASS_TABLE.map(({ color }) => [
    Number.parseInt(color.slice(1, 3), 16),
    Number.parseInt(color.slice(3, 5), 16),
    Number.parseInt(color.slice(5, 7), 16),
  ]);
  const projected = new THREE.Vector3();
  const worldPoint = new THREE.Vector3();
  const paint = (pixels: ImageData, depth: Float32Array, x: number, y: number,
    value: number, color: number[], closer: boolean) => {
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const px = x + dx, py = y + dy;
      if (px < 0 || px >= pixels.width || py < 0 || py >= pixels.height) continue;
      const index = py * pixels.width + px;
      if (closer ? value >= depth[index] : value <= depth[index]) continue;
      depth[index] = value;
      const offset = index * 4;
      pixels.data[offset] = color[0];
      pixels.data[offset + 1] = color[1];
      pixels.data[offset + 2] = color[2];
    }
  };
  const lateral = maxRange * Math.tan(0.7);
  for (const point of scan.points) {
    const color = rgbBytes[point.class_id] ?? rgbBytes[0];
    projected.set(...point.xyz_sensor).applyMatrix4(lidarToCamera);
    if (projected.z >= rgb.min_range_m && projected.z <= rgb.max_range_m) {
      const u = rgb.camera.fx_px * projected.x / projected.z + rgb.camera.cx_px;
      const v = rgb.camera.fy_px * projected.y / projected.z + rgb.camera.cy_px;
      if (u >= 0 && u < cloud.width && v >= 0 && v < cloud.height)
        paint(cameraPixels, cameraDepth, Math.floor(u), Math.floor(v), projected.z, color, true);
    }
    const [forward, left] = point.xyz_sensor;
    const x = Math.floor(overhead.width * (0.5 - left / (2 * lateral)));
    const y = Math.floor(overhead.height * (1 - forward / maxRange));
    worldPoint.set(...point.xyz_sensor).applyMatrix4(worldFromLidar);
    paint(overheadPixels, overheadHeight, x, y, worldPoint.y, color, false);
  }
  cloudContext.putImageData(cameraPixels, 0, 0);
  overheadContext.putImageData(overheadPixels, 0, 0);
  return {
    range_png_base64: dataUrlBase64(range.toDataURL("image/png")),
    cloud_png_base64: dataUrlBase64(cloud.toDataURL("image/png")),
    topdown_png_base64: dataUrlBase64(overhead.toDataURL("image/png")),
  };
}

function addChunk(root: THREE.Group, data: ChunkData) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(data.mesh.positions, 3));
  geometry.setAttribute("normal", new THREE.BufferAttribute(data.mesh.normals, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(data.mesh.colors, 3));
  const terrain = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    vertexColors: true, flatShading: true, roughness: 1,
  }));
  terrain.name = `terrain:${data.mesh.coord.x},${data.mesh.coord.z}`;
  terrain.userData.lidar_class = "terrain";
  terrain.receiveShadow = true;
  root.add(terrain);
  for (const placement of data.placements) {
    const geometry = placement.kind === "tree"
      ? new THREE.ConeGeometry(0.46 * placement.scale, 2.5 * placement.scale, 6)
      : new THREE.DodecahedronGeometry(placement.scale, 0);
    const material = new THREE.MeshStandardMaterial({
      color: placement.kind === "tree" ? 0x425c3d : 0x82735f,
      flatShading: true,
      roughness: 1,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = placement.id;
    mesh.userData.lidar_class = placement.kind === "tree" ? "vegetation" : "rock";
    mesh.position.set(...placement.position);
    mesh.rotation.y = placement.yaw;
    if (placement.kind === "tree") mesh.position.y += 1.25 * placement.scale;
    root.add(mesh);
  }
}

async function capture(request: Request) {
  validatePayload("WorldSpec", request.world);
  validatePayload("RigSpec", request.rig);
  validatePayload("EnvironmentSpec", request.environment);
  validatePayload("CapturePlan", request.plan);
  validateRigGeometry(request.rig);
  if (request.plan.simulation_time_s !== request.environment.simulation_time_s)
    throw new Error("Capture plan and environment ticks differ");
  if (!request.plan.modalities.includes("rgb"))
    throw new Error("Capture requires the synchronized RGB/reference passes");
  const world = createWorld(request.world);
  const rgb = captureCamera(request.rig, "rgb");
  const position = [
    rgb.T_world_from_sensor[3],
    rgb.T_world_from_sensor[7],
    rgb.T_world_from_sensor[11],
  ] as [number, number, number];
  const lidarRequested = request.plan.modalities.includes("lidar");
  const lidarRig = request.rig.sensors.find((sensor) => sensor.modality === "lidar");
  if (lidarRequested && !lidarRig?.available)
    throw new Error("Requested LiDAR sensor is unavailable");
  const lidarOrigin = lidarRequested ? beamFor(request.rig, 0, 0).origin : null;
  const coords = sensorChunks(world, [
    { position, range: rgb.max_range_m },
    ...(lidarOrigin && lidarRig ? [{ position: lidarOrigin, range: lidarRig.max_range_m }] : []),
  ]);
  const chunks = coords.map((coord) => ({
    mesh: meshChunk(world, coord, 2),
    placements: chunkPlacements(world, coord),
    generationMs: 0,
  }));
  const scene = new THREE.Scene();
  const response = weatherResponse(request.environment);
  scene.background = new THREE.Color(0xcbd5d8);
  scene.add(new THREE.HemisphereLight(0xf9f4e4, 0x626856,
    0.25 + 1.75 * response.rgb_illumination));
  const sun = new THREE.DirectionalLight(0xfff0d5,
    3 * Math.max(0, request.environment.sun_direction_world[1]));
  sun.position.set(...request.environment.sun_direction_world);
  scene.add(sun);
  const root = new THREE.Group();
  chunks.forEach((chunk) => addChunk(root, chunk));
  scene.add(root);
  let assets: AssetLibrary | null = null;
  let site: ReturnType<typeof buildAerodromeScene> | null = null;
  let catalog: Catalog | null = null;
  if (request.world.instances.length) {
    catalog = await loadCatalog();
    assets = new AssetLibrary(catalog);
    await assets.load(request.world, AbortSignal.timeout(30_000));
  }
  if (assets || [HARBOR_GENERATOR, AERODROME_GENERATOR].includes(request.world.generator_version)) {
    site = buildAerodromeScene(request.world, assets, coords);
    scene.add(site.root);
  }
  const renderer = new THREE.WebGLRenderer({
    antialias: false,
    preserveDrawingBuffer: false,
    powerPreference: "high-performance",
  });
  document.body.appendChild(renderer.domElement);
  const capabilities = rendererCapabilities(renderer);
  if (!capabilities.webgl2 || !capabilities.float_readback)
    throw new Error("worker_context_lost: required WebGL2 float readback unavailable");
  const started = performance.now();
  try {
    const capture = renderReferencePasses(
      renderer,
      scene,
      request.rig,
      request.world.instances.map((item) => item.instance_id).sort(),
      request.environment,
      request.plan.seed_channels.rgb,
      request.plan.seed_channels.weather,
    );
    let thermal: ReturnType<typeof renderThermalPass> | null = null;
    let thermalStateJson: string | null = null;
    if (request.plan.modalities.includes("ir")) {
      const records = catalog?.assets ?? [];
      const thermalState = request.environment.thermal_history === "continued"
        ? advanceThermalState(
            decodeThermalState(request._thermal_state_json ?? ""),
            request.world,
            records,
            request.environment,
          )
        : initializeThermalState(request.world, records, request.environment);
      thermalStateJson = encodeThermalState(thermalState);
      thermal = renderThermalPass(
        renderer,
        scene,
        request.rig,
        records,
        thermalState,
        request.environment,
        request.plan.seed_channels.ir,
      );
      if (thermal.width !== capture.width || thermal.height !== capture.height)
        throw new Error("The synchronized v1 RGB and IR cameras require matching raster dimensions");
    }
    let lidar: ReturnType<typeof scanLidar> | null = null;
    let lidarPreview: ReturnType<typeof lidarPreviews> | null = null;
    let lidarGeometry: ReturnType<typeof buildLidarScene> | null = null;
    try {
      if (lidarRequested) {
        lidarGeometry = buildLidarScene(scene, catalog?.assets ?? []);
        lidar = scanLidar(lidarGeometry, request.rig, request.plan.seed_channels.lidar, {
          environment: request.environment,
          weather_seed: request.plan.seed_channels.weather,
        });
        lidarPreview = lidarPreviews(lidar, request.rig, lidarRig!.max_range_m);
      }
    } finally {
      lidarGeometry?.dispose();
    }
    const count = lidar?.points.length ?? 0;
    const xyz = new Float32Array(count * 3);
    const intensity = new Float32Array(count);
    const beamIds = new Uint32Array(count);
    const timeOffsets = new Float32Array(count);
    const validity = new Uint8Array(count);
    const classRef = new Uint8Array(count);
    for (let i = 0; i < count; i++) {
      const point = lidar!.points[i];
      xyz.set(point.xyz_sensor, i * 3);
      intensity[i] = point.intensity;
      beamIds[i] = point.beam_id;
      timeOffsets[i] = point.time_offset_s;
      validity[i] = 1;
      classRef[i] = point.class_id;
    }
    const idealRange = new Float32Array(lidar?.beam_status.length ?? 0);
    const idealInstance = new Uint32Array(idealRange.length);
    const idealClass = new Uint8Array(idealRange.length);
    for (let i = 0; i < idealRange.length; i++) {
      const hit = lidar!.ideal_hits[i];
      if (!hit) continue;
      idealRange[i] = hit.range_m;
      idealInstance[i] = hit.instance_id ? capture.instanceIds[hit.instance_id] ?? 0 : 0;
      idealClass[i] = hit.class_id;
    }
    return {
      width: capture.width,
      height: capture.height,
      tick_s: request.plan.simulation_time_s,
      instance_ids: capture.instanceIds,
      rgb_png_base64: dataUrlBase64(capture.rgbPng),
      depth_preview_png_base64: dataUrlBase64(capture.depthPreviewPng),
      instance_preview_png_base64: dataUrlBase64(capture.instancePreviewPng),
      depth_f32_base64: bytesBase64(new Uint8Array(capture.depth.buffer)),
      instance_u32_base64: bytesBase64(new Uint8Array(capture.instance.buffer)),
      ir_preview_png_base64: thermal ? dataUrlBase64(thermal.previewPng) : null,
      ir_radiance_f32_base64: thermal ? bytesBase64(new Uint8Array(thermal.radiance.buffer)) : null,
      ir_validity_u8_base64: thermal ? bytesBase64(thermal.validity) : null,
      ir_saturation_u8_base64: thermal ? bytesBase64(thermal.saturation) : null,
      thermal_state_json: thermalStateJson,
      ir_calibration: thermal?.calibration ?? null,
      lidar_calibration: lidar ? {
        version: lidar.version, sensor_id: lidar.sensor_id,
        frame: "lidar-forward-left-up", rows: lidar.rows, columns: lidar.columns,
        horizontal_fov_rad: lidarRig!.lidar!.horizontal_fov_rad,
        vertical_fov_rad: lidarRig!.lidar!.vertical_fov_rad,
        scan_duration_s: lidarRig!.scan_duration_s,
        timestamp_offset_s: lidarRig!.timestamp_offset_s,
        min_range_m: lidarRig!.min_range_m, max_range_m: lidarRig!.max_range_m,
        T_world_from_rig: request.rig.T_world_from_rig,
        T_rig_from_sensor: lidarRig!.T_rig_from_sensor,
        beam_order: "row-major; rows top-to-bottom, columns left-to-right",
        status_codes: { no_return: 0, surface: 1, receiver_dropout: 2,
          particle: 3, atmospheric_dropout: 4 },
        response: lidar.response,
        class_schema_version: "lidar-semantic.v1",
        class_table: LIDAR_CLASS_TABLE,
        cloud_preview_projection: "rgb-camera-perspective",
        topdown_preview_projection: "lidar-sensor-overhead",
      } : null,
      lidar_point_count: count,
      weather_calibration: response,
      lidar_xyz_f32_base64: lidar ? bytesBase64(new Uint8Array(xyz.buffer)) : null,
      lidar_intensity_f32_base64: lidar ? bytesBase64(new Uint8Array(intensity.buffer)) : null,
      lidar_beam_id_u32_base64: lidar ? bytesBase64(new Uint8Array(beamIds.buffer)) : null,
      lidar_time_offset_f32_base64: lidar ? bytesBase64(new Uint8Array(timeOffsets.buffer)) : null,
      lidar_validity_u8_base64: lidar ? bytesBase64(validity) : null,
      lidar_class_ref_u8_base64: lidar ? bytesBase64(classRef) : null,
      lidar_beam_status_u8_base64: lidar ? bytesBase64(lidar.beam_status) : null,
      lidar_ideal_range_f32_base64: lidar ? bytesBase64(new Uint8Array(idealRange.buffer)) : null,
      lidar_ideal_instance_u32_base64: lidar ? bytesBase64(new Uint8Array(idealInstance.buffer)) : null,
      lidar_ideal_class_u8_base64: lidar ? bytesBase64(idealClass) : null,
      lidar_range_preview_png_base64: lidarPreview?.range_png_base64 ?? null,
      lidar_cloud_preview_png_base64: lidarPreview?.cloud_png_base64 ?? null,
      lidar_topdown_preview_png_base64: lidarPreview?.topdown_png_base64 ?? null,
      capabilities,
      elapsed_ms: performance.now() - started,
      resident_chunks: coords.map(({ x, z }) => `${x},${z}@2`),
    };
  } finally {
    site?.dispose();
    assets?.dispose();
    scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.geometry.dispose();
      for (const material of Array.isArray(object.material) ? object.material : [object.material])
        material.dispose();
    });
    scene.clear();
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
  }
}

function capabilities() {
  const renderer = new THREE.WebGLRenderer({ antialias: false });
  document.body.appendChild(renderer.domElement);
  try {
    return rendererCapabilities(renderer);
  } finally {
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
  }
}

declare global {
  interface Window {
    captureJob: typeof capture;
    captureCapabilities: typeof capabilities;
  }
}
window.captureJob = capture;
window.captureCapabilities = capabilities;
