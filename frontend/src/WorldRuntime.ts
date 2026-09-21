import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  createWorld,
  ChunkCache,
  displayChunks,
  SensorResidency,
  validateBookmark,
  type ChunkLease,
  type RigBookmark,
  type Vec3,
} from "@yulab/world";
import type { WorldSpec } from "@yulab/contracts";
import { ChunkWorker } from "./ChunkWorker";
import { ChunkScene } from "./ChunkScene";

declare global {
  interface Window {
    worldQA?: WorldRuntime;
  }
}

const percentile = (values: number[], q: number) =>
  [...values].sort((a, b) => a - b)[Math.floor((values.length - 1) * q)] ?? 0;
const record = (values: number[], n: number, limit = 4096) => {
  values.push(n);
  if (values.length > limit) values.shift();
};
export type WorldStatus = {
  ready: boolean;
  chunks: number;
  triangles: number;
  trees: number;
  rocks: number;
  milliseconds: number;
  x: number;
  z: number;
  error: string;
};

export class WorldRuntime {
  readonly world;
  readonly worker;
  readonly cache;
  readonly sensorWorker;
  readonly sensorCache;
  readonly sensors;
  readonly renderer;
  readonly camera = new THREE.PerspectiveCamera(42, 1, 0.5, 2000);
  readonly controls;
  readonly chunks = new ChunkScene();
  readonly scene = new THREE.Scene();
  navigation: "orbit" | "flight" = "orbit";
  pitch: 2 | 4 = 4;
  private lease: ChunkLease | null = null;
  private request: AbortController | null = null;
  private sensorRequest = new AbortController();
  private desired = "";
  private running = false;
  private disposed = false;
  private frame = 0;
  private observer;
  private keys = new Set<string>();
  private drag = false;
  private previous = performance.now();
  private frames: number[] = [];
  private generation: number[] = [];
  private commitTimes: number[] = [];
  private sun = new THREE.DirectionalLight("#fff0d5", 3);
  private status: WorldStatus = {
    ready: false,
    chunks: 0,
    triangles: 0,
    trees: 0,
    rocks: 0,
    milliseconds: 0,
    x: 0,
    z: 0,
    error: "",
  };
  constructor(
    readonly spec: WorldSpec,
    private mount: HTMLDivElement,
    private onStatus: (status: WorldStatus) => void,
  ) {
    this.world = createWorld(spec);
    this.worker = new ChunkWorker(spec);
    this.sensorWorker = new ChunkWorker(spec);
    this.cache = new ChunkCache(async (coord, pitch, signal) => {
      const data = await this.worker.generate(coord, pitch, signal);
      record(this.generation, data.generationMs, 512);
      return data;
    });
    this.sensorCache = new ChunkCache(
      this.sensorWorker.generate,
      32,
      128 * 1024 * 1024,
    );
    this.sensors = new SensorResidency(this.world, this.sensorCache);
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.shadowMap.autoUpdate = false;
    const canvas = this.renderer.domElement;
    canvas.tabIndex = 0;
    canvas.setAttribute("aria-label", "World navigation canvas");
    mount.appendChild(canvas);
    this.scene.background = new THREE.Color("#e7e9e4");
    this.scene.add(
      new THREE.HemisphereLight("#f9f4e4", "#626856", 2),
      this.chunks.root,
      this.sun,
      this.sun.target,
    );
    this.sun.castShadow = true;
    Object.assign(this.sun.shadow.camera, {
      left: -260,
      right: 260,
      top: 260,
      bottom: -260,
      near: 1,
      far: 500,
    });
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.normalBias = 0.2;
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = false;
    this.controls.minDistance = 8;
    this.controls.maxDistance = 650;
    this.controls.maxPolarAngle = Math.PI * 0.52;
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(mount);
    this.resize();
    canvas.addEventListener("keydown", this.keyDown);
    canvas.addEventListener("keyup", this.keyUp);
    canvas.addEventListener("blur", this.blur);
    canvas.addEventListener("pointerdown", this.pointerDown);
    canvas.addEventListener("pointermove", this.pointerMove);
    canvas.addEventListener("pointerup", this.pointerUp);
    window.addEventListener("blur", this.blur);
    this.frame = requestAnimationFrame(this.draw);
  }
  private resize() {
    const { width, height } = this.mount.getBoundingClientRect();
    this.renderer.setSize(width, height);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }
  private keyDown = (e: KeyboardEvent) => {
    if (
      this.navigation === "flight" &&
      [
        "KeyW",
        "KeyA",
        "KeyS",
        "KeyD",
        "KeyQ",
        "KeyE",
        "ShiftLeft",
        "ShiftRight",
      ].includes(e.code)
    ) {
      e.preventDefault();
      this.keys.add(e.code);
    }
  };
  private keyUp = (e: KeyboardEvent) => {
    this.keys.delete(e.code);
  };
  private blur = () => {
    this.keys.clear();
    this.drag = false;
  };
  private pointerDown = (e: PointerEvent) => {
    this.renderer.domElement.focus();
    if (this.navigation === "flight" && e.button === 0) {
      this.drag = true;
      this.renderer.domElement.setPointerCapture(e.pointerId);
    }
  };
  private pointerUp = () => {
    this.drag = false;
  };
  private pointerMove = (e: PointerEvent) => {
    if (!this.drag || this.navigation !== "flight") return;
    const rotation = new THREE.Euler().setFromQuaternion(
      this.camera.quaternion,
      "YXZ",
    );
    rotation.y -= e.movementX * 0.003;
    rotation.x = THREE.MathUtils.clamp(
      rotation.x - e.movementY * 0.003,
      -1.5,
      1.5,
    );
    this.camera.quaternion.setFromEuler(rotation);
    this.updateFlightTarget();
  };
  private updateFlightTarget() {
    this.controls.target
      .copy(this.camera.position)
      .addScaledVector(this.camera.getWorldDirection(new THREE.Vector3()), 20);
    this.clamp(this.controls.target);
  }
  private clamp(v: THREE.Vector3) {
    v.x = THREE.MathUtils.clamp(v.x, -1023.99, 1023.99);
    v.z = THREE.MathUtils.clamp(v.z, -1023.99, 1023.99);
    v.y = THREE.MathUtils.clamp(v.y, -24, 800);
  }
  private draw = (now: number) => {
    if (this.disposed) return;
    const elapsed = now - this.previous;
    this.previous = now;
    if (elapsed > 0) record(this.frames, elapsed);
    if (this.navigation === "flight") {
      const forward = this.camera.getWorldDirection(new THREE.Vector3()),
        right = new THREE.Vector3(1, 0, 0).applyQuaternion(
          this.camera.quaternion,
        );
      const delta = new THREE.Vector3()
        .addScaledVector(
          forward,
          Number(this.keys.has("KeyW")) - Number(this.keys.has("KeyS")),
        )
        .addScaledVector(
          right,
          Number(this.keys.has("KeyD")) - Number(this.keys.has("KeyA")),
        );
      delta.y += Number(this.keys.has("KeyE")) - Number(this.keys.has("KeyQ"));
      if (delta.lengthSq())
        this.camera.position.addScaledVector(
          delta.normalize(),
          (Math.min(elapsed, 50) / 1000) *
            (this.keys.has("ShiftLeft") || this.keys.has("ShiftRight")
              ? 150
              : 45),
        );
      this.clamp(this.camera.position);
      this.updateFlightTarget();
    } else {
      this.clamp(this.controls.target);
      this.controls.update();
      this.clamp(this.camera.position);
    }
    const focus =
      this.navigation === "flight"
        ? this.camera.position
        : this.controls.target;
    const desired = `${Math.floor(focus.x / 128)},${Math.floor(focus.z / 128)}@${this.pitch}`;
    if (desired !== this.desired) {
      this.desired = desired;
      this.request?.abort();
      void this.pump();
    }
    this.renderer.render(this.scene, this.camera);
    this.frame = requestAnimationFrame(this.draw);
  };
  private publish(change: Partial<WorldStatus>) {
    this.status = { ...this.status, ...change };
    if (!this.disposed) this.onStatus(this.status);
  }
  private async pump() {
    if (this.running || this.disposed) return;
    this.running = true;
    while (!this.disposed) {
      const desired = this.desired,
        pitch = this.pitch;
      const focus =
        this.navigation === "flight"
          ? this.camera.position
          : this.controls.target;
      const x = focus.x,
        z = focus.z;
      const request = new AbortController();
      this.request = request;
      this.publish({ ready: false, error: "", x, z });
      const start = performance.now();
      try {
        const lease = await this.cache.acquire(
          displayChunks(this.world, x, z),
          pitch,
          request.signal,
        );
        if (
          this.disposed ||
          request.signal.aborted ||
          desired !== this.desired
        ) {
          lease.release();
          continue;
        }
        const commit = performance.now();
        try {
          this.chunks.commit(lease.chunks);
        } catch (error) {
          lease.release();
          throw error;
        }
        this.lease?.release();
        this.lease = lease;
        this.sun.position.set(x - 180, 250, z + 170);
        this.sun.target.position.set(x, 20, z);
        this.renderer.shadowMap.needsUpdate = true;
        record(this.commitTimes, performance.now() - commit, 512);
        let triangles = 0,
          trees = 0,
          rocks = 0;
        for (const d of lease.chunks.values()) {
          triangles += d.mesh.positions.length / 9;
          trees += d.placements.filter((p) => p.kind === "tree").length;
          rocks += d.placements.filter((p) => p.kind === "rock").length;
        }
        this.publish({
          ready: true,
          chunks: lease.chunks.size,
          triangles,
          trees,
          rocks,
          milliseconds: Math.round(performance.now() - start),
        });
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError"))
          this.publish({
            ready: false,
            error: error instanceof Error ? error.message : String(error),
          });
      }
      if (desired === this.desired) break;
    }
    this.running = false;
  }
  setPitch(pitch: 2 | 4) {
    this.pitch = pitch;
  }
  setNavigation(mode: "orbit" | "flight") {
    this.navigation = mode;
    this.controls.enabled = mode === "orbit";
    this.keys.clear();
    if (mode === "flight") {
      this.camera.position
        .copy(this.controls.target)
        .add(new THREE.Vector3(0, 80, 100));
      this.clamp(this.camera.position);
      this.camera.lookAt(this.controls.target);
      this.updateFlightTarget();
    }
  }
  view(index: number, view: string) {
    const c = this.spec.features[index] ?? this.spec.features[0],
      [x, y, z] = c.center_m;
    this.navigation = "orbit";
    this.controls.enabled = true;
    if (view === "top") {
      this.camera.position.set(x, 540, z + 0.01);
      this.controls.target.set(x, 12, z);
    } else if (view === "opening") {
      this.camera.position.set(
        x + c.extent_m[0] * 0.08,
        y,
        z + c.extent_m[2] * 0.95,
      );
      this.controls.target.set(x, y, z);
    } else if (view === "detail") {
      this.camera.position.set(
        x + c.extent_m[0] * 0.82,
        y + c.extent_m[1] * 0.65,
        z + c.extent_m[2] * 0.98,
      );
      this.controls.target.set(x, y, z);
    } else {
      this.camera.position.set(x + 310, 225, z + 350);
      this.controls.target.set(x, 20, z);
    }
    this.clamp(this.camera.position);
    this.controls.update();
  }
  moveTo(x: number, z: number) {
    if (![x, z].every(Number.isFinite))
      throw new Error("Position must be finite");
    const focus =
      this.navigation === "flight"
        ? this.camera.position
        : this.controls.target;
    const offset = new THREE.Vector3(x - focus.x, 0, z - focus.z);
    this.camera.position.add(offset);
    this.controls.target.add(offset);
    this.clamp(this.camera.position);
    this.clamp(this.controls.target);
  }
  bookmark(name: string): RigBookmark {
    return validateBookmark(
      {
        version: "rig-bookmark.v1",
        name,
        world: this.spec,
        position: this.camera.position.toArray(),
        quaternion: this.camera.quaternion.toArray(),
        target: this.controls.target.toArray(),
        navigation: this.navigation,
        pitch: this.pitch,
      },
      this.spec,
    );
  }
  restore(value: unknown) {
    const b = validateBookmark(value, this.spec);
    this.navigation = b.navigation;
    this.controls.enabled = b.navigation === "orbit";
    this.pitch = b.pitch;
    this.camera.position.set(...b.position);
    this.camera.quaternion.set(...b.quaternion);
    this.controls.target.set(...b.target);
    this.keys.clear();
  }
  async prepareSensors(position: Vec3, range: number) {
    return this.sensors.capture(
      [{ position, range }],
      this.sensorRequest.signal,
      async (chunks) => ({
        keys: [...chunks.keys()],
        pitch: 2,
        ids: [...chunks.values()].flatMap((d) => d.placements.map((p) => p.id)),
      }),
    );
  }
  metrics() {
    const gl = this.renderer.getContext(),
      debug = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      status: this.status,
      desired: this.desired,
      keys: [...(this.lease?.chunks.keys() ?? [])],
      ids: [...(this.lease?.chunks.values() ?? [])].flatMap((d) =>
        d.placements.map((p) => p.id),
      ),
      cache: this.cache.snapshot(),
      sensorCache: this.sensorCache.snapshot(),
      worker: { ...this.worker.stats },
      resources: { ...this.chunks.stats },
      renderer: {
        ...this.renderer.info.memory,
        calls: this.renderer.info.render.calls,
        triangles: this.renderer.info.render.triangles,
      },
      frame: {
        samples: this.frames.length,
        p50: percentile(this.frames, 0.5),
        p95: percentile(this.frames, 0.95),
        max: Math.max(0, ...this.frames),
      },
      generation: {
        samples: this.generation.length,
        p50: percentile(this.generation, 0.5),
        p95: percentile(this.generation, 0.95),
      },
      commit: {
        p50: percentile(this.commitTimes, 0.5),
        p95: percentile(this.commitTimes, 0.95),
      },
      gpu: debug
        ? (gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) as string)
        : "unavailable",
      canvas: [this.renderer.domElement.width, this.renderer.domElement.height],
      heap:
        (performance as Performance & { memory?: { usedJSHeapSize: number } })
          .memory?.usedJSHeapSize ?? null,
    };
  }
  resetMetrics() {
    this.frames = [];
    this.generation = [];
    this.commitTimes = [];
  }
  dispose() {
    this.disposed = true;
    this.request?.abort();
    this.sensorRequest.abort();
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.controls.dispose();
    this.blur();
    window.removeEventListener("blur", this.blur);
    const canvas = this.renderer.domElement;
    canvas.removeEventListener("keydown", this.keyDown);
    canvas.removeEventListener("keyup", this.keyUp);
    canvas.removeEventListener("blur", this.blur);
    canvas.removeEventListener("pointerdown", this.pointerDown);
    canvas.removeEventListener("pointermove", this.pointerMove);
    canvas.removeEventListener("pointerup", this.pointerUp);
    this.lease?.release();
    this.lease = null;
    this.worker.dispose();
    this.sensorWorker.dispose();
    this.cache.dispose();
    this.sensorCache.dispose();
    this.chunks.dispose();
    this.sun.shadow.dispose();
    this.scene.clear();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    canvas.remove();
  }
}
