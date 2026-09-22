import * as THREE from "three";
import type { RigSpec } from "@yulab/contracts";
import {
  captureCamera,
  decodeInstanceId,
  encodeInstanceId,
  flipRows,
  shouldCaptureObject,
} from "./index.ts";

export type ReferenceCapture = {
  width: number;
  height: number;
  rgbPng: string;
  depthPreviewPng: string;
  instancePreviewPng: string;
  depth: Float32Array;
  instance: Uint32Array;
  instanceIds: Record<string, number>;
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

function makeCamera(rig: RigSpec) {
  const capture = captureCamera(rig, "rgb"), c = capture.camera;
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

/** Fixed-rig RGB, metric depth and exact instance-ID passes at one frozen tick. */
export function renderReferencePasses(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  rig: RigSpec,
  orderedInstanceIds: readonly string[],
): ReferenceCapture {
  const gl = renderer.getContext();
  if (!gl.getExtension("EXT_color_buffer_float"))
    throw new Error("worker_context_lost: float color-buffer readback unavailable");
  const { camera, capture } = makeCamera(rig), c = capture.camera;
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
    return {
      width, height, depth, instance, instanceIds,
      rgbPng: pngDataUrl(rgb, width, height),
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
