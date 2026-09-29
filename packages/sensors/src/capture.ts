import * as THREE from "three";
import type { AssetRecord, EnvironmentSpec, RigSpec } from "@yulab/contracts";
import {
  captureCamera,
  decodeInstanceId,
  encodeInstanceId,
  flipRows,
  shouldCaptureObject,
} from "./index.ts";
import {
  LWIR_BAND_UM,
  LWIR_RESPONSE_VERSION,
  THERMAL_MODEL_VERSION,
  THERMAL_STATE_VERSION,
  bandRadiance,
  radianceRaster,
  surfaceRadiance,
  thermalPreviewRgba,
  type ThermalState,
} from "./thermal.ts";
import { applyIrAtmosphere, applyRgbWeather, weatherResponse } from "./weather.ts";

export const IR_NOISE_SIGMA_W_PER_M2_SR = 0.02;
export const IR_SATURATION_W_PER_M2_SR = 200;
export const IR_PREVIEW_SCALE_W_PER_M2_SR = [bandRadiance(270), bandRadiance(450)] as const;

export type ReferenceCapture = {
  width: number;
  height: number;
  rgbPng: string;
  rgbRaw: Uint8Array;
  depthPreviewPng: string;
  instancePreviewPng: string;
  depth: Float32Array;
  instance: Uint32Array;
  instanceIds: Record<string, number>;
};

export type ThermalCapture = {
  width: number;
  height: number;
  previewPng: string;
  radiance: Float32Array;
  validity: Uint8Array;
  saturation: Uint8Array;
  calibration: {
    response_version: typeof LWIR_RESPONSE_VERSION;
    band_um: [8, 14];
    radiance_units: "W/m2/sr";
    noise_sigma_w_per_m2_sr: number;
    saturation_w_per_m2_sr: number;
    thermal_model_version: typeof THERMAL_MODEL_VERSION;
    thermal_state_version: typeof THERMAL_STATE_VERSION;
    preview_palette: "iron-v1";
    preview_scale: [number, number];
    palette_applies_to_raw: false;
    atmosphere_version?: "weather-response.v1";
    extinction_per_m?: number;
    path_radiance_w_per_m2_sr?: number;
  };
};

function pngDataUrl(bytes: Uint8Array, width: number, height: number) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("2D preview canvas unavailable");
  context.putImageData(new ImageData(new Uint8ClampedArray(bytes), width, height), 0, 0);
  return canvas.toDataURL("image/png");
}

function makeCamera(rig: RigSpec, modality: "rgb" | "ir") {
  const capture = captureCamera(rig, modality), c = capture.camera;
  const camera = new THREE.PerspectiveCamera();
  camera.near = capture.min_range_m;
  camera.far = capture.max_range_m;
  camera.projectionMatrix.set(
    2 * c.fx_px / c.width_px, 0, 1 - 2 * c.cx_px / c.width_px, 0,
    0, 2 * c.fy_px / c.height_px, 2 * c.cy_px / c.height_px - 1, 0,
    0, 0, -(camera.far + camera.near) / (camera.far - camera.near),
    -2 * camera.far * camera.near / (camera.far - camera.near),
    0, 0, -1, 0,
  );
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
  camera.matrixAutoUpdate = false;
  camera.matrixWorld.set(
    capture.T_world_from_camera[0], capture.T_world_from_camera[1], capture.T_world_from_camera[2], capture.T_world_from_camera[3],
    capture.T_world_from_camera[4], capture.T_world_from_camera[5], capture.T_world_from_camera[6], capture.T_world_from_camera[7],
    capture.T_world_from_camera[8], capture.T_world_from_camera[9], capture.T_world_from_camera[10], capture.T_world_from_camera[11],
    capture.T_world_from_camera[12], capture.T_world_from_camera[13], capture.T_world_from_camera[14], capture.T_world_from_camera[15],
  );
  camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
  return { camera, capture };
}

function target(width: number, height: number, type: THREE.TextureDataType) {
  const value = new THREE.WebGLRenderTarget(width, height, {
    format: THREE.RGBAFormat,
    type,
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
    depthBuffer: true,
    stencilBuffer: false,
  });
  value.texture.generateMipmaps = false;
  return value;
}

/** Geometry-only labels. Each camera gets its own depth-tested ID raster. */
export function renderVisibilityPass(
  renderer: THREE.WebGLRenderer, scene: THREE.Scene, rig: RigSpec,
  modality: "rgb" | "ir", orderedInstanceIds: readonly string[],
) {
  const { camera, capture } = makeCamera(rig, modality);
  const width = capture.camera.width_px, height = capture.camera.height_px;
  const renderTarget = target(width, height, THREE.UnsignedByteType);
  const priorTarget = renderer.getRenderTarget();
  const priorBackground = scene.background;
  const priorTone = renderer.toneMapping;
  const priorColor = renderer.outputColorSpace;
  const materials = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
  const visibility = new Map<THREE.Object3D, boolean>();
  const idMaterials = new Map<number, THREE.ShaderMaterial>();
  const materialFor = (id: number) => {
    let result = idMaterials.get(id);
    if (!result) {
      const [r, g, b] = encodeInstanceId(id);
      result = new THREE.ShaderMaterial({
        vertexShader: `void main() { vec4 p=vec4(position,1.0);
          #ifdef USE_INSTANCING
          p=instanceMatrix*p;
          #endif
          gl_Position=projectionMatrix*modelViewMatrix*p; }`,
        fragmentShader: `void main() { gl_FragColor=vec4(${r}.0/255.0,${g}.0/255.0,${b}.0/255.0,1.0); }`,
        side: THREE.DoubleSide, toneMapped: false,
      });
      idMaterials.set(id, result);
    }
    return result;
  };
  const roots = orderedInstanceIds.map((name) => scene.getObjectByName(name));
  const rootFor = (object: THREE.Object3D) => {
    for (let node: THREE.Object3D | null = object; node; node = node.parent) {
      const index = roots.indexOf(node);
      if (index >= 0) return index;
    }
    return -1;
  };
  scene.updateMatrixWorld(true);
  scene.traverse((object) => {
    visibility.set(object, object.visible);
    if (!shouldCaptureObject(object)) object.visible = false;
    if (object instanceof THREE.Mesh) {
      materials.set(object, object.material);
      const index = rootFor(object);
      object.material = materialFor(index + 1);
    }
  });
  const pixels = new Uint8Array(width * height * 4);
  const read = () => {
    renderer.setRenderTarget(renderTarget);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    renderer.readRenderTargetPixels(renderTarget, 0, 0, width, height, pixels);
    const top = flipRows(pixels, width, height, 4);
    const ids = new Uint32Array(width * height);
    for (let i = 0; i < ids.length; i++) ids[i] = decodeInstanceId(top.subarray(i * 4, i * 4 + 3));
    return ids;
  };
  try {
    scene.background = null;
    renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;
    const visible = read();
    const isolated: Record<string, number> = {};
    const truncated: Record<string, boolean> = {};
    for (let index = 0; index < roots.length; index++) {
      const root = roots[index];
      if (!root) throw new Error(`Missing instance root ${orderedInstanceIds[index]}`);
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh)
          object.visible = visibility.get(object)! && rootFor(object) === index;
      });
      const own = read();
      let count = 0;
      for (const id of own) if (id === index + 1) count++;
      isolated[orderedInstanceIds[index]] = count;
      // The frustum is convex: a mesh lies wholly inside exactly when every
      // vertex lies inside. Test authored vertices, not an overlarge world AABB.
      let crossesFrustum = false;
      if (count) root.traverse((object) => {
        if (crossesFrustum || !(object instanceof THREE.Mesh)) return;
        const position = object.geometry.getAttribute("position");
        if (!position) return;
        const point = new THREE.Vector3();
        for (let vertex = 0; vertex < position.count; vertex++) {
          point.fromBufferAttribute(position, vertex).applyMatrix4(object.matrixWorld).project(camera);
          if (point.x < -1 || point.x > 1 || point.y < -1 || point.y > 1 ||
              point.z < -1 || point.z > 1) {
            crossesFrustum = true;
            break;
          }
        }
      });
      truncated[orderedInstanceIds[index]] = crossesFrustum;
    }
    return { width, height, visible, isolated, truncated };
  } finally {
    materials.forEach((material, mesh) => mesh.material = material);
    visibility.forEach((value, object) => object.visible = value);
    idMaterials.forEach((material) => material.dispose());
    scene.background = priorBackground;
    renderer.toneMapping = priorTone;
    renderer.outputColorSpace = priorColor;
    renderer.setRenderTarget(priorTarget);
    renderTarget.dispose();
  }
}

/** Fixed-rig RGB, metric depth and exact instance-ID passes at one frozen tick. */
export function renderReferencePasses(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  rig: RigSpec,
  orderedInstanceIds: readonly string[],
  environment?: EnvironmentSpec,
  rgbSeed = 0,
  weatherSeed = 0,
): ReferenceCapture {
  const gl = renderer.getContext();
  if (!gl.getExtension("EXT_color_buffer_float"))
    throw new Error("worker_context_lost: float color-buffer readback unavailable");
  const { camera, capture } = makeCamera(rig, "rgb"), c = capture.camera;
  const width = c.width_px, height = c.height_px;
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  renderer.setClearColor(0x000000, 1);
  scene.updateMatrixWorld(true);
  const visibility = new Map<THREE.Object3D, boolean>();
  scene.traverse((object) => {
    visibility.set(object, object.visible);
    if (!shouldCaptureObject(object)) object.visible = false;
  });
  const restoreVisibility = () => visibility.forEach((value, object) => object.visible = value);
  const rgbTarget = target(width, height, THREE.UnsignedByteType);
  const depthTarget = target(width, height, THREE.FloatType);
  const idTarget = target(width, height, THREE.UnsignedByteType);
  const previousTarget = renderer.getRenderTarget();
  const previousOverride = scene.overrideMaterial;
  const previousToneMapping = renderer.toneMapping;
  const previousColorSpace = renderer.outputColorSpace;
  const previousBackground = scene.background;
  try {
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.setRenderTarget(rgbTarget);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    const rgbBottom = new Uint8Array(width * height * 4);
    renderer.readRenderTargetPixels(rgbTarget, 0, 0, width, height, rgbBottom);
    const rgb = flipRows(rgbBottom, width, height, 4);

    const depthMaterial = new THREE.ShaderMaterial({
      vertexShader: `
        varying float vDepth;
        void main() {
          vec4 p = vec4(position, 1.0);
          #ifdef USE_INSTANCING
            p = instanceMatrix * p;
          #endif
          vec4 view = modelViewMatrix * p;
          vDepth = -view.z;
          gl_Position = projectionMatrix * view;
        }
      `,
      fragmentShader: `
        precision highp float;
        varying float vDepth;
        void main() { gl_FragColor = vec4(vDepth, 0.0, 0.0, 1.0); }
      `,
      side: THREE.DoubleSide,
      toneMapped: false,
    });
    scene.overrideMaterial = depthMaterial;
    scene.background = null;
    renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.setRenderTarget(depthTarget);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    const depthBottom = new Float32Array(width * height * 4);
    renderer.readRenderTargetPixels(depthTarget, 0, 0, width, height, depthBottom);
    const depthRgba = flipRows(depthBottom, width, height, 4);
    const depth = new Float32Array(width * height);
    for (let i = 0; i < depth.length; i++) depth[i] = depthRgba[i * 4];
    depthMaterial.dispose();

    scene.overrideMaterial = null;
    const originalMaterials = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
    const idMaterials = new Map<number, THREE.ShaderMaterial>();
    const materialFor = (id: number) => {
      let material = idMaterials.get(id);
      if (!material) {
        const [r, g, b] = encodeInstanceId(id);
        material = new THREE.ShaderMaterial({
          vertexShader: `
            void main() {
              vec4 p = vec4(position, 1.0);
              #ifdef USE_INSTANCING
                p = instanceMatrix * p;
              #endif
              gl_Position = projectionMatrix * modelViewMatrix * p;
            }
          `,
          fragmentShader: `
            precision highp float;
            void main() { gl_FragColor = vec4(${r}.0/255.0, ${g}.0/255.0, ${b}.0/255.0, 1.0); }
          `,
          side: THREE.DoubleSide,
          toneMapped: false,
        });
        idMaterials.set(id, material);
      }
      return material;
    };
    scene.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      originalMaterials.set(object, object.material);
      object.material = materialFor(0);
    });
    const instanceIds: Record<string, number> = {};
    orderedInstanceIds.forEach((name, index) => {
      const id = index + 1;
      if (id > 0xff_ff_ff) throw new Error("Instance-ID capacity exceeded");
      instanceIds[name] = id;
      const root = scene.getObjectByName(name);
      if (!root) return;
      root.traverse((object) => {
        if (object instanceof THREE.Mesh) object.material = materialFor(id);
      });
    });
    renderer.setRenderTarget(idTarget);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    const idBottom = new Uint8Array(width * height * 4);
    renderer.readRenderTargetPixels(idTarget, 0, 0, width, height, idBottom);
    const idRgba = flipRows(idBottom, width, height, 4);
    const instance = new Uint32Array(width * height);
    for (let i = 0; i < instance.length; i++)
      instance[i] = decodeInstanceId(idRgba.subarray(i * 4, i * 4 + 3));
    originalMaterials.forEach((material, mesh) => mesh.material = material);
    idMaterials.forEach((material) => material.dispose());

    const depthPreview = new Uint8Array(width * height * 4);
    for (let i = 0; i < depth.length; i++) {
      const shade = depth[i] > 0 ? Math.max(1, Math.round(255 * (1 - depth[i] / camera.far))) : 0;
      depthPreview.set([shade, shade, shade, 255], i * 4);
    }
    const instancePreview = new Uint8Array(width * height * 4);
    for (let i = 0; i < instance.length; i++) {
      const id = instance[i];
      const offset = i * 4;
      if (id) {
        instancePreview[offset] = 64 + (id * 97) % 192;
        instancePreview[offset + 1] = 64 + (id * 57) % 192;
        instancePreview[offset + 2] = 64 + (id * 137) % 192;
      }
      instancePreview[offset + 3] = 255;
    }
    const weatherRgb = environment
      ? applyRgbWeather(rgb, depth, width, height, environment, rgbSeed, weatherSeed) : rgb;
    const rgbRaw = new Uint8Array(width * height * 3);
    for (let i = 0; i < width * height; i++) rgbRaw.set(weatherRgb.subarray(i * 4, i * 4 + 3), i * 3);
    return {
      width, height, depth, instance, instanceIds,
      rgbRaw,
      rgbPng: pngDataUrl(weatherRgb, width, height),
      depthPreviewPng: pngDataUrl(depthPreview, width, height),
      instancePreviewPng: pngDataUrl(instancePreview, width, height),
    };
  } finally {
    scene.overrideMaterial = previousOverride;
    scene.background = previousBackground;
    renderer.toneMapping = previousToneMapping;
    renderer.outputColorSpace = previousColorSpace;
    renderer.setRenderTarget(previousTarget);
    restoreVisibility();
    rgbTarget.dispose();
    depthTarget.dispose();
    idTarget.dispose();
  }
}

function owningInstance(object: THREE.Object3D) {
  let current: THREE.Object3D | null = object;
  while (current) {
    if (typeof current.userData.instance_id === "string") return current;
    current = current.parent;
  }
  return null;
}

function meshEmissivity(mesh: THREE.Mesh, record: AssetRecord) {
  const partByNode = new Map(record.parts.map((part) => [part.mesh_node, part]));
  const materialById = new Map(record.materials.map((material) => [material.id, material]));
  const names = Array.isArray(mesh.userData.source_parts)
    ? mesh.userData.source_parts.map(String)
    : [];
  let weighted = 0;
  let area = 0;
  for (const name of names) {
    const part = partByNode.get(name);
    const material = part && materialById.get(part.material_id);
    if (!material) continue;
    weighted += material.emissivity * material.area_m2;
    area += material.area_m2;
  }
  return area > 0 ? weighted / area : 0.9;
}

/** Depth-tested LWIR pass. Scene lights and RGB material colors are deliberately ignored. */
export function renderThermalPass(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  rig: RigSpec,
  assets: readonly AssetRecord[],
  state: ThermalState,
  environment: EnvironmentSpec,
  noiseSeed: number,
): ThermalCapture {
  const gl = renderer.getContext();
  if (!gl.getExtension("EXT_color_buffer_float"))
    throw new Error("worker_context_lost: float color-buffer readback unavailable");
  const { camera, capture } = makeCamera(rig, "ir"), c = capture.camera;
  const width = c.width_px, height = c.height_px;
  renderer.setPixelRatio(1);
  renderer.setSize(width, height, false);
  scene.updateMatrixWorld(true);
  const assetById = new Map(assets.map((asset) => [asset.asset_id, asset]));
  const temperatureByRegion = new Map(state.nodes.map((node) => [
    `${node.instance_id}\0${node.region_id}`,
    node.temperature_k,
  ]));
  const reflected = bandRadiance(environment.ambient_temperature_k);
  const originalMaterials = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
  const originalVisibility = new Map<THREE.Object3D, boolean>();
  const thermalMaterials = new Map<string, THREE.ShaderMaterial>();
  const materialFor = (radiance: number) => {
    const key = radiance.toPrecision(12);
    let material = thermalMaterials.get(key);
    if (!material) {
      material = new THREE.ShaderMaterial({
        vertexShader: `
          varying float vDepth;
          void main() {
            vec4 p = vec4(position, 1.0);
            #ifdef USE_INSTANCING
              p = instanceMatrix * p;
            #endif
            vec4 view = modelViewMatrix * p;
            vDepth = -view.z;
            gl_Position = projectionMatrix * view;
          }
        `,
        fragmentShader: `
          precision highp float;
          varying float vDepth;
          void main() { gl_FragColor = vec4(${radiance.toPrecision(12)}, vDepth, 0.0, 1.0); }
        `,
        side: THREE.DoubleSide,
        toneMapped: false,
      });
      thermalMaterials.set(key, material);
    }
    return material;
  };
  scene.traverse((object) => {
    originalVisibility.set(object, object.visible);
    if (!shouldCaptureObject(object)) object.visible = false;
    if (!(object instanceof THREE.Mesh)) return;
    originalMaterials.set(object, object.material);
    const owner = owningInstance(object);
    const instanceId = owner?.userData.instance_id;
    const assetId = owner?.userData.asset_id;
    const semantic = String(object.userData.semantic ?? "background-surface");
    const record = typeof assetId === "string" ? assetById.get(assetId) : undefined;
    const temperature = typeof instanceId === "string"
      ? temperatureByRegion.get(`${instanceId}\0${semantic}`) ?? environment.ambient_temperature_k
      : environment.ambient_temperature_k;
    const emissivity = record ? meshEmissivity(object, record) : 0.95;
    object.material = materialFor(surfaceRadiance(temperature, emissivity, reflected));
  });
  const renderTarget = target(width, height, THREE.FloatType);
  const previousTarget = renderer.getRenderTarget();
  const previousToneMapping = renderer.toneMapping;
  const previousColorSpace = renderer.outputColorSpace;
  const previousBackground = scene.background;
  const previousClear = renderer.getClearColor(new THREE.Color()).clone();
  const previousClearAlpha = renderer.getClearAlpha();
  try {
    scene.background = null;
    renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.setClearColor(0x000000, 1);
    renderer.setRenderTarget(renderTarget);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    const bottom = new Float32Array(width * height * 4);
    renderer.readRenderTargetPixels(renderTarget, 0, 0, width, height, bottom);
    const rgba = flipRows(bottom, width, height, 4);
    const clean = new Float32Array(width * height);
    const validity = new Uint8Array(width * height);
    const weather = weatherResponse(environment);
    for (let i = 0; i < clean.length; i++) {
      const surface = rgba[i * 4];
      validity[i] = surface > 0 ? 1 : 0;
      if (validity[i]) clean[i] = applyIrAtmosphere(surface, rgba[i * 4 + 1], weather);
    }
    const response = radianceRaster(clean, validity, {
      seed: noiseSeed,
      noise_sigma: weather.ir_noise_sigma_w_per_m2_sr,
      saturation_w_per_m2_sr: IR_SATURATION_W_PER_M2_SR,
    });
    const preview = thermalPreviewRgba(response.radiance, validity, {
      min_w_per_m2_sr: IR_PREVIEW_SCALE_W_PER_M2_SR[0],
      max_w_per_m2_sr: IR_PREVIEW_SCALE_W_PER_M2_SR[1],
      palette: "iron-v1",
    });
    return {
      width,
      height,
      previewPng: pngDataUrl(preview, width, height),
      radiance: response.radiance,
      validity,
      saturation: response.saturation,
      calibration: {
        response_version: LWIR_RESPONSE_VERSION,
        band_um: [...LWIR_BAND_UM],
        radiance_units: "W/m2/sr",
        noise_sigma_w_per_m2_sr: weather.ir_noise_sigma_w_per_m2_sr,
        saturation_w_per_m2_sr: IR_SATURATION_W_PER_M2_SR,
        thermal_model_version: THERMAL_MODEL_VERSION,
        thermal_state_version: THERMAL_STATE_VERSION,
        preview_palette: "iron-v1",
        preview_scale: [...IR_PREVIEW_SCALE_W_PER_M2_SR],
        palette_applies_to_raw: false,
        atmosphere_version: weather.version,
        extinction_per_m: weather.ir_extinction_per_m,
        path_radiance_w_per_m2_sr: weather.ir_path_radiance_w_per_m2_sr,
      },
    };
  } finally {
    originalMaterials.forEach((material, mesh) => mesh.material = material);
    originalVisibility.forEach((visible, object) => object.visible = visible);
    thermalMaterials.forEach((material) => material.dispose());
    scene.background = previousBackground;
    renderer.toneMapping = previousToneMapping;
    renderer.outputColorSpace = previousColorSpace;
    renderer.setClearColor(previousClear, previousClearAlpha);
    renderer.setRenderTarget(previousTarget);
    renderTarget.dispose();
  }
}

export function rendererCapabilities(renderer: THREE.WebGLRenderer) {
  const gl = renderer.getContext();
  const debug = gl.getExtension("WEBGL_debug_renderer_info");
  return {
    webgl2: renderer.capabilities.isWebGL2,
    float_readback: Boolean(gl.getExtension("EXT_color_buffer_float")),
    renderer: debug ? String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : "unavailable",
    vendor: debug ? String(gl.getParameter(debug.UNMASKED_VENDOR_WEBGL)) : "unavailable",
    max_texture_size: gl.getParameter(gl.MAX_TEXTURE_SIZE) as number,
  };
}
