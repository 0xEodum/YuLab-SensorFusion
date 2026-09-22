import * as THREE from "three";
import { AssetLibrary, buildAerodromeScene, loadCatalog } from "@yulab/assets";
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
  renderReferencePasses,
  rendererCapabilities,
  validateRigGeometry,
} from "@yulab/sensors";

type Request = {
  world: WorldSpec;
  rig: RigSpec;
  environment: EnvironmentSpec;
  plan: CapturePlan;
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

function addChunk(root: THREE.Group, data: ChunkData) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(data.mesh.positions, 3));
  geometry.setAttribute("normal", new THREE.BufferAttribute(data.mesh.normals, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(data.mesh.colors, 3));
  const terrain = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    vertexColors: true, flatShading: true, roughness: 1,
  }));
  terrain.name = `terrain:${data.mesh.coord.x},${data.mesh.coord.z}`;
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
    throw new Error("SF-05 requires an RGB capture request");
  const world = createWorld(request.world);
  const rgb = captureCamera(request.rig, "rgb");
  const position = [
    rgb.T_world_from_sensor[3],
    rgb.T_world_from_sensor[7],
    rgb.T_world_from_sensor[11],
  ] as [number, number, number];
  const coords = sensorChunks(world, [{ position, range: rgb.max_range_m }]);
  const chunks = coords.map((coord) => ({
    mesh: meshChunk(world, coord, 2),
    placements: chunkPlacements(world, coord),
    generationMs: 0,
  }));
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xcbd5d8);
  scene.add(new THREE.HemisphereLight(0xf9f4e4, 0x626856, 2));
  const sun = new THREE.DirectionalLight(0xfff0d5, 3);
  sun.position.set(-180, 250, 170);
  scene.add(sun);
  const root = new THREE.Group();
  chunks.forEach((chunk) => addChunk(root, chunk));
  scene.add(root);
  let assets: AssetLibrary | null = null;
  let site: ReturnType<typeof buildAerodromeScene> | null = null;
  if (request.world.instances.length) {
    const catalog = await loadCatalog();
    assets = new AssetLibrary(catalog);
    await assets.load(request.world, AbortSignal.timeout(30_000));
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
    );
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
