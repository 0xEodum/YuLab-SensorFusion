import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import type { AssetRecord, WorldSpec } from "@yulab/contracts";
import { validatePayload } from "@yulab/contracts/validate";
import {
  aerodromeStructures,
  harborStructures,
  harborShoreX,
  HARBOR_GENERATOR,
  HARBOR_WATER_Y,
  type ChunkCoord,
  type Structure,
} from "@yulab/world";

export type Catalog = { version: "asset-catalog.v1"; assets: AssetRecord[] };
export function validateCatalog(value: unknown): Catalog {
  const c = value as Catalog;
  if (!c || c.version !== "asset-catalog.v1" || !Array.isArray(c.assets))
    throw new Error("catalog: unsupported version or asset list");
  const ids = new Set<string>();
  for (const record of c.assets) {
    validatePayload("AssetRecord", record);
    if (!/^[a-z0-9-]+$/.test(record.asset_id) || ids.has(record.asset_id))
      throw new Error(`${record.asset_id}: invalid or duplicate catalog ID`);
    ids.add(record.asset_id);
    if (record.mesh.sha256 !== record.content_sha256)
      throw new Error(`${record.asset_id}: inconsistent mesh identity`);
  }
  for (const id of ["f16", "rq4", "ground-vehicle", "cruiser", "destroyer",
    "a10", "f14", "f16xl", "f18", "f22", "mq9", "su35",
    "complex-radar", "simulation-radar", "spaa"])
    if (!ids.has(id))
      throw new Error(`${id}: required catalog record is missing`);
  return c;
}
export async function loadCatalog(signal?: AbortSignal) {
  const response = await fetch("/catalog/catalog.json", { signal });
  if (!response.ok) throw new Error(`catalog: HTTP ${response.status}`);
  return validateCatalog(await response.json());
}
export function disposeObject(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>(),
    materials = new Set<THREE.Material>(),
    textures = new Set<THREE.Texture>();
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    geometries.add(o.geometry);
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
      materials.add(m);
      for (const v of Object.values(m))
        if (v instanceof THREE.Texture) textures.add(v);
    }
  });
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => m.dispose());
  textures.forEach((t) => t.dispose());
}

/** Merge only matching material AND semantic regions; thermal identity stays explicit. */
function batchTemplate(root: THREE.Group) {
  const groups = new Map<
    string,
    {
      material: THREE.Material;
      geometries: THREE.BufferGeometry[];
      names: string[];
      semantic: string;
      articulation?: string;
      pivot?: [number, number, number];
    }
  >();
  root.updateMatrixWorld(true);
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh) || Array.isArray(o.material)) return;
    const semantic = String(o.userData.semantic ?? "body-surface");
    const articulation = o.userData.articulation === "turret-yaw" ? "turret-yaw" : undefined;
    const pivot = articulation ? o.userData.pivot_m as [number, number, number] : undefined;
    if (articulation && (!Array.isArray(pivot) || pivot.length !== 3 || !pivot.every(Number.isFinite)))
      throw new Error("catalog: articulated turret has no finite pivot");
    const key = `${o.material.uuid}:${semantic}:${articulation ?? "fixed"}:${Object.keys(o.geometry.attributes).sort().join(",")}`;
    let g = groups.get(key);
    if (!g) {
      g = { material: o.material, geometries: [], names: [], semantic, articulation, pivot };
      groups.set(key, g);
    } else if (articulation && g.pivot?.some((value, i) => value !== pivot![i])) {
      throw new Error("catalog: turret parts disagree on pivot");
    }
    const geometry = o.geometry.clone().applyMatrix4(o.matrixWorld);
    g.geometries.push(geometry.index ? geometry.toNonIndexed() : geometry);
    g.names.push(o.name);
  });
  const out = new THREE.Group();
  for (const [index, g] of [...groups.values()].entries()) {
    const geometry = mergeGeometries(g.geometries);
    g.geometries.forEach((v) => v.dispose());
    if (!geometry)
      throw new Error("catalog: incompatible geometry for batching");
    const mesh = new THREE.Mesh(geometry, g.material);
    mesh.name = `batch-${index}`;
    mesh.userData = { semantic: g.semantic, source_parts: g.names };
    mesh.castShadow = mesh.receiveShadow = true;
    if (g.articulation === "turret-yaw") {
      const pivot = g.pivot!;
      geometry.translate(-pivot[0], -pivot[1], -pivot[2]);
      let turret = out.getObjectByName("turret-yaw") as THREE.Group | undefined;
      if (!turret) {
        turret = new THREE.Group();
        turret.name = "turret-yaw";
        turret.position.set(...pivot);
        out.add(turret);
      }
      turret.add(mesh);
    } else out.add(mesh);
  }
  root.traverse((o) => {
    if (o instanceof THREE.Mesh) o.geometry.dispose();
  });
  return out;
}

export class AssetLibrary {
  readonly templates = new Map<string, THREE.Group>();
  private disposed = false;
  readonly catalog: Catalog;
  constructor(catalog: Catalog) {
    this.catalog = catalog;
  }
  async load(spec: WorldSpec, signal: AbortSignal) {
    const fetchSignal = AbortSignal.any([signal, AbortSignal.timeout(30000)]);
    for (const id of new Set(spec.instances.map((i) => i.asset_id))) {
      const record = this.catalog.assets.find((a) => a.asset_id === id);
      if (!record) throw new Error(`${id}: missing catalog record`);
      if (
        spec.instances.some(
          (i) => i.asset_id === id && i.asset_sha256 !== record.content_sha256,
        )
      )
        throw new Error(`${id}: world asset hash mismatch`);
      try {
        const response = await fetch(`/catalog/${id}.glb`, {
          signal: fetchSignal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const bytes = await response.arrayBuffer();
        const actual = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        )
          .map((v) => v.toString(16).padStart(2, "0"))
          .join("");
        if (
          actual !== record.content_sha256 ||
          bytes.byteLength !== record.mesh.byte_length
        )
          throw new Error("GLB integrity mismatch");
        const metadataResponse = await fetch(`/catalog/${id}.metadata.json`, {
          signal: fetchSignal,
        });
        if (!metadataResponse.ok)
          throw new Error(`metadata HTTP ${metadataResponse.status}`);
        const metadataBytes = await metadataResponse.arrayBuffer();
        const metadataHash = Array.from(
          new Uint8Array(await crypto.subtle.digest("SHA-256", metadataBytes)),
        )
          .map((v) => v.toString(16).padStart(2, "0"))
          .join("");
        if (
          metadataHash !== record.metadata.sha256 ||
          metadataBytes.byteLength !== record.metadata.byte_length
        )
          throw new Error("metadata integrity mismatch");
        const metadata = JSON.parse(new TextDecoder().decode(metadataBytes));
        if (
          metadata.version !== "asset-import.v1" ||
          metadata.axes !== "+X left, +Y up, +Z forward"
        )
          throw new Error("unsupported metadata profile");
        const gltf = await new GLTFLoader().parseAsync(bytes, "");
        if (signal.aborted || this.disposed) {
          disposeObject(gltf.scene);
          throw new DOMException("Cancelled", "AbortError");
        }
        const names = new Set<string>();
        gltf.scene.traverse((o) => names.add(o.name));
        if (record.parts.some((p) => !names.has(p.mesh_node))) {
          disposeObject(gltf.scene);
          throw new Error("GLB semantic node missing");
        }
        const template = batchTemplate(gltf.scene);
        this.templates.set(id, template);
      } catch (e) {
        throw new Error(`${id}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  }
  instantiate(instance: WorldSpec["instances"][number]) {
    const template = this.templates.get(instance.asset_id);
    if (!template) throw new Error(`${instance.asset_id}: asset not ready`);
    const object = template.clone(true);
    object.name = instance.instance_id;
    object.userData = {
      instance_id: instance.instance_id,
      asset_id: instance.asset_id,
    };
    const turret = object.getObjectByName("turret-yaw");
    if (turret) {
      // FNV-1a gives each persistent instance an independent, replayable pose.
      let value = 2166136261;
      for (const character of instance.instance_id) {
        value ^= character.charCodeAt(0);
        value = Math.imul(value, 16777619);
      }
      turret.rotation.y = ((value >>> 0) / 4294967296 * 2 - 1) * Math.PI;
      object.userData.turret_yaw_rad = turret.rotation.y;
    }
    object.applyMatrix4(
      new THREE.Matrix4().set(...instance.T_world_from_asset),
    );
    return object;
  }
  dispose() {
    this.disposed = true;
    this.templates.forEach(disposeObject);
    this.templates.clear();
  }
}

const intersects = (
  x: number,
  z: number,
  hx: number,
  hz: number,
  c: ChunkCoord,
) =>
  x + hx >= c.x * 128 &&
  x - hx <= (c.x + 1) * 128 &&
  z + hz >= c.z * 128 &&
  z - hz <= (c.z + 1) * 128;

/** Same geometry for display and sensor residency. Membership uses bounds, never camera/frustum. */
export function buildAerodromeScene(
  spec: WorldSpec,
  library: AssetLibrary | null,
  coords: ChunkCoord[],
) {
  const root = new THREE.Group(),
    owned: THREE.Mesh[] = [];
  const add = (s: Structure, center = s.center, size = s.size) => {
    const geometry = new THREE.BoxGeometry(...size);
    const material = new THREE.MeshStandardMaterial({
      color: s.color,
      roughness: 0.85,
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = s.id;
    mesh.position.set(...center);
    mesh.castShadow = s.kind === "building";
    mesh.receiveShadow = true;
    mesh.userData = { background: true, lidar_class: s.kind };
    root.add(mesh);
    owned.push(mesh);
  };
  for (const s of spec.generator_version === HARBOR_GENERATOR
    ? harborStructures() : aerodromeStructures(
      spec.world_id.startsWith("aerodrome-catalog-") ? "catalog" : "fixtures")) {
    if (s.kind === "pavement" || s.kind === "marking") {
      // Clip the long runway and roads to loaded terrain; no floating distant pavement.
      for (const c of coords) {
        const loX = Math.max(s.center[0] - s.size[0] / 2, c.x * 128),
          hiX = Math.min(s.center[0] + s.size[0] / 2, (c.x + 1) * 128);
        const loZ = Math.max(s.center[2] - s.size[2] / 2, c.z * 128),
          hiZ = Math.min(s.center[2] + s.size[2] / 2, (c.z + 1) * 128);
        if (hiX > loX && hiZ > loZ)
          add(
            s,
            [(loX + hiX) / 2, s.center[1], (loZ + hiZ) / 2],
            [hiX - loX, s.size[1], hiZ - loZ],
          );
      }
    } else if (
      coords.some((c) =>
        intersects(s.center[0], s.center[2], s.size[0] / 2, s.size[2] / 2, c),
      )
    )
      add(s);
  }
  if (spec.generator_version === HARBOR_GENERATOR) {
      const positions: number[] = [], colors: number[] = [];
      const color = new THREE.Color();
      const vertex = (x: number, z: number) => {
        const shore = harborShoreX(z, spec.seed) - 3;
        const px = Math.min(x, shore);
        const wave = Math.sin(px * 0.115 + z * 0.075) * 0.032 +
          Math.sin(px * 0.032 - z * 0.09) * 0.024;
        positions.push(px, HARBOR_WATER_Y + wave, z);
        const tone = 0.5 + 0.5 * Math.sin(px * 0.051 + z * 0.083);
        const foam = Math.max(0, 1 - (shore - px) / 15) *
          (0.35 + 0.65 * Math.sin(z * 0.12 + px * 0.06) ** 2);
        color.setRGB(0.045 + tone * 0.018 + foam * 0.12,
          0.165 + tone * 0.024 + foam * 0.13,
          0.205 + tone * 0.028 + foam * 0.11, THREE.LinearSRGBColorSpace);
        colors.push(color.r, color.g, color.b);
      };
      // Water is a world-wide environmental surface, independent of terrain
      // display residency. A 16 m pitch keeps its distant horizon continuous.
      for (let x0 = spec.origin_m[0]; x0 < 96; x0 += 16)
        for (let z0 = spec.origin_m[2]; z0 < spec.origin_m[2] + spec.extent_m[2]; z0 += 16) {
        const x1 = x0 + 16, z1 = z0 + 16;
        if (x0 >= Math.max(harborShoreX(z0, spec.seed),
          harborShoreX(z1, spec.seed))) continue;
        vertex(x0, z0); vertex(x1, z0); vertex(x1, z1);
        vertex(x0, z0); vertex(x1, z1); vertex(x0, z1);
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      geometry.computeVertexNormals();
      const material = new THREE.MeshStandardMaterial({
        vertexColors: true, roughness: 0.38, metalness: 0.08,
        side: THREE.DoubleSide,
      });
      const water = new THREE.Mesh(geometry, material);
      water.name = "harbor-water";
      water.receiveShadow = true;
      water.userData = { background: true, lidar_class: "water" };
      root.add(water);
      owned.push(water);
  }
  const ids: string[] = [];
  for (const instance of spec.instances) {
    if (!library) throw new Error("catalog: required for asset world");
    const record = library.catalog.assets.find(
      (a) => a.asset_id === instance.asset_id,
    )!;
    const m = new THREE.Matrix4().set(...instance.T_world_from_asset);
    const box = new THREE.Box3()
      .setFromCenterAndSize(
        new THREE.Vector3(...record.bounds.center_m),
        new THREE.Vector3(...record.bounds.extent_m),
      )
      .applyMatrix4(m);
    const center = box.getCenter(new THREE.Vector3()),
      size = box.getSize(new THREE.Vector3());
    if (
      coords.some((c) =>
        intersects(center.x, center.z, size.x / 2, size.z / 2, c),
      )
    ) {
      root.add(library.instantiate(instance));
      ids.push(instance.instance_id);
    }
  }
  return {
    root,
    ids,
    dispose: () => {
      for (const m of owned) {
        m.geometry.dispose();
        (m.material as THREE.Material).dispose();
      }
      root.clear();
    },
  };
}
