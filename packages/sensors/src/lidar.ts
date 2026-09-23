import * as THREE from "three";
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from "three-mesh-bvh";
import type { AssetRecord, RigSpec } from "@yulab/contracts";
import { shouldCaptureObject, validateRigGeometry } from "./index.ts";

export const LIDAR_MODEL_VERSION = "lidar-first-return.v1";
export const LIDAR_STATUS = { no_return: 0, surface: 1, receiver_dropout: 2 } as const;
type Vec3 = [number, number, number];
export type LidarHit = {
  range_m: number;
  point_world: Vec3;
  normal_world: Vec3;
  object_name: string;
  instance_id: string | null;
  face_index: number;
};
type Entry = { mesh: THREE.Mesh; box: THREE.Box3; order: number };
type Node = { box: THREE.Box3; left?: Node; right?: Node; entries?: Entry[] };

function lidarSensor(rig: RigSpec) {
  validateRigGeometry(rig);
  const sensor = rig.sensors.find((s) => s.modality === "lidar");
  if (!sensor?.available || !sensor.lidar) throw new Error("LiDAR sensor is unavailable");
  if (!Number.isInteger(sensor.lidar.rows) || !Number.isInteger(sensor.lidar.columns) ||
      sensor.lidar.rows < 1 || sensor.lidar.columns < 1 ||
      !(sensor.min_range_m >= 0) || !(sensor.max_range_m > sensor.min_range_m) ||
      !(sensor.scan_duration_s >= 0)) throw new Error("Invalid LiDAR beam/range specification");
  return sensor;
}

function matrix(values: readonly number[]) {
  return new THREE.Matrix4().set(...values as Parameters<THREE.Matrix4["set"]>);
}

function beamAt(sensor: RigSpec["sensors"][number], transform: THREE.Matrix4, row: number, column: number) {
  const pattern = sensor.lidar!;
  if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || row >= pattern.rows || column < 0 || column >= pattern.columns)
    throw new Error("LiDAR beam index is outside the pattern");
  const azimuth = pattern.columns === 1 ? 0 : (0.5 - column / (pattern.columns - 1)) * pattern.horizontal_fov_rad;
  const elevation = pattern.rows === 1 ? 0 : (0.5 - row / (pattern.rows - 1)) * pattern.vertical_fov_rad;
  const origin = new THREE.Vector3().setFromMatrixPosition(transform);
  const directionSensor = new THREE.Vector3(
    Math.cos(elevation) * Math.cos(azimuth),
    Math.cos(elevation) * Math.sin(azimuth),
    Math.sin(elevation),
  );
  const direction = directionSensor.clone().transformDirection(transform);
  const beamId = row * pattern.columns + column;
  const total = pattern.rows * pattern.columns;
  return {
    beam_id: beamId, row, column, azimuth_rad: azimuth, elevation_rad: elevation,
    time_offset_s: sensor.timestamp_offset_s + (total === 1 ? 0 : sensor.scan_duration_s * beamId / (total - 1)),
    origin: origin.toArray() as Vec3,
    direction: direction.toArray() as Vec3,
    direction_sensor: directionSensor.toArray() as Vec3,
  };
}

export function beamFor(rig: RigSpec, row: number, column: number) {
  const sensor = lidarSensor(rig);
  return beamAt(sensor, matrix(rig.T_world_from_rig).multiply(matrix(sensor.T_rig_from_sensor)), row, column);
}

function nodeFor(entries: Entry[]): Node {
  const box = new THREE.Box3();
  for (const entry of entries) box.union(entry.box);
  if (entries.length <= 8) return { box, entries };
  const size = box.getSize(new THREE.Vector3());
  const axis = size.x >= size.y && size.x >= size.z ? "x" : size.y >= size.z ? "y" : "z";
  entries.sort((a, b) => (a.box.min[axis] + a.box.max[axis]) - (b.box.min[axis] + b.box.max[axis]) || a.order - b.order);
  const half = entries.length >>> 1;
  return { box, left: nodeFor(entries.slice(0, half)), right: nodeFor(entries.slice(half)) };
}

function instanceOf(mesh: THREE.Object3D): { instance_id: string | null; asset_id: string | null } {
  for (let node: THREE.Object3D | null = mesh; node; node = node.parent)
    if (typeof node.userData.instance_id === "string")
      return { instance_id: node.userData.instance_id, asset_id: String(node.userData.asset_id ?? "") };
  return { instance_id: null, asset_id: null };
}

function opaque(mesh: THREE.Mesh, catalog: readonly AssetRecord[]) {
  const { asset_id } = instanceOf(mesh);
  if (!asset_id) return true;
  const record = catalog.find((item) => item.asset_id === asset_id);
  if (!record) throw new Error(`${asset_id}: LiDAR asset metadata missing`);
  const names = mesh.userData.source_parts as string[] | undefined;
  if (!names?.length) return true;
  return names.every((name) => {
    const part = record.parts.find((item) => item.mesh_node === name);
    const material = record.materials.find((item) => item.id === part?.material_id);
    if (!part || !material) throw new Error(`${asset_id}: LiDAR material metadata missing for ${name}`);
    return material.opaque_lidar;
  });
}

/** Mesh BVHs accelerate triangles; a second BVH culls whole scene meshes. */
export function buildLidarScene(root: THREE.Object3D, catalog: readonly AssetRecord[] = []) {
  root.updateMatrixWorld(true);
  const entries: Entry[] = [];
  const geometries = new Set<THREE.BufferGeometry>();
  let triangles = 0;
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || !shouldCaptureObject(object) || !opaque(object, catalog)) return;
    const geometry = object.geometry;
    if (!geometry.getAttribute("position")) return;
    if (!geometries.has(geometry)) {
      geometry.computeBoundsTree = computeBoundsTree;
      geometry.disposeBoundsTree = disposeBoundsTree;
      geometry.computeBoundsTree({ targetLeafSize: 16 });
      geometries.add(geometry);
      triangles += geometry.index ? geometry.index.count / 3 : geometry.getAttribute("position").count / 3;
    }
    // Double-sided opaque geometry lets scans from inside a solid see its exit face.
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
    mesh.name = object.name;
    mesh.userData = { ...object.userData, ...instanceOf(object) };
    mesh.matrixAutoUpdate = false;
    mesh.matrixWorld.copy(object.matrixWorld);
    mesh.raycast = acceleratedRaycast;
    const box = new THREE.Box3().setFromObject(mesh);
    if (!box.isEmpty()) entries.push({ mesh, box, order: entries.length });
  });
  const tree = entries.length ? nodeFor(entries.slice()) : null;
  const raycaster = new THREE.Raycaster();
  raycaster.firstHitOnly = true;
  const point = new THREE.Vector3();
  return {
    mesh_count: entries.length,
    triangle_count: triangles,
    first(origin: Vec3, direction: Vec3, near: number, far: number): LidarHit | null {
      raycaster.set(new THREE.Vector3(...origin), new THREE.Vector3(...direction));
      raycaster.near = near;
      raycaster.far = far;
      const ray = raycaster.ray;
      let best: (LidarHit & { order: number }) | null = null;
      const visit = (node: Node) => {
        if (!ray.intersectBox(node.box, point)) return;
        const lower = node.box.containsPoint(ray.origin) ? 0 : point.distanceTo(ray.origin);
        if (best && lower > best.range_m + 1e-9) return;
        if (node.entries) {
          for (const entry of node.entries) {
            if (!ray.intersectBox(entry.box, point)) continue;
            const hit = raycaster.intersectObject(entry.mesh, false)[0];
            if (!hit) continue;
            const faceIndex = hit.faceIndex ?? 0;
            if (best && (hit.distance > best.range_m + 1e-9 ||
              (Math.abs(hit.distance - best.range_m) <= 1e-9 &&
               (entry.order > best.order || (entry.order === best.order && faceIndex >= best.face_index))))) continue;
            const normal = hit.face?.normal.clone().transformDirection(entry.mesh.matrixWorld) ?? new THREE.Vector3();
            best = {
              range_m: hit.distance, point_world: hit.point.toArray() as Vec3,
              normal_world: normal.toArray() as Vec3,
              object_name: entry.mesh.name,
              instance_id: instanceOf(entry.mesh).instance_id,
              face_index: faceIndex, order: entry.order,
            };
          }
        } else {
          if (node.left) visit(node.left);
          if (node.right) visit(node.right);
        }
      };
      if (tree) visit(tree);
      const found = best as (LidarHit & { order: number }) | null;
      if (!found) return null;
      return {
        range_m: found.range_m, point_world: found.point_world,
        normal_world: found.normal_world, object_name: found.object_name,
        instance_id: found.instance_id, face_index: found.face_index,
      };
    },
    dispose() {
      for (const entry of entries) (entry.mesh.material as THREE.Material).dispose();
      for (const geometry of geometries) geometry.disposeBoundsTree();
    },
  };
}

function uniform(seed: number, beam: number, stream: number) {
  let x = (seed ^ Math.imul(beam + 1, 0x9e3779b1) ^ Math.imul(stream + 1, 0x85ebca6b)) >>> 0;
  x ^= x >>> 16; x = Math.imul(x, 0x7feb352d); x ^= x >>> 15;
  x = Math.imul(x, 0x846ca68b); x ^= x >>> 16;
  return ((x >>> 0) + 0.5) / 0x100000000;
}
function gaussian(seed: number, beam: number, stream: number) {
  return Math.sqrt(-2 * Math.log(uniform(seed, beam, stream))) *
    Math.cos(2 * Math.PI * uniform(seed, beam, stream + 1));
}

export function scanLidar(
  scene: ReturnType<typeof buildLidarScene>, rig: RigSpec, seed: number,
  options: { dropout_probability?: number; range_sigma_m?: number; intensity_sigma?: number } = {},
) {
  const sensor = lidarSensor(rig), pattern = sensor.lidar!;
  const dropout = options.dropout_probability ?? 0;
  const rangeSigma = options.range_sigma_m ?? 0.003;
  const intensitySigma = options.intensity_sigma ?? 0.01;
  if (![dropout, rangeSigma, intensitySigma].every(Number.isFinite) || dropout < 0 || dropout > 1 || rangeSigma < 0 || intensitySigma < 0)
    throw new Error("Invalid LiDAR receiver response parameters");
  const total = pattern.rows * pattern.columns;
  const worldFromSensor = matrix(rig.T_world_from_rig).multiply(matrix(sensor.T_rig_from_sensor));
  const beamStatus = new Uint8Array(total);
  const idealHits: (LidarHit | null)[] = new Array(total).fill(null);
  const points: { xyz_sensor: Vec3; intensity: number; beam_id: number; time_offset_s: number; range_m: number }[] = [];
  const sensorFromWorld = worldFromSensor.clone().invert();
  for (let row = 0; row < pattern.rows; row++) for (let column = 0; column < pattern.columns; column++) {
    const beam = beamAt(sensor, worldFromSensor, row, column);
    const hit = scene.first(beam.origin, beam.direction, sensor.min_range_m, sensor.max_range_m);
    idealHits[beam.beam_id] = hit;
    if (!hit) continue;
    const incidence = Math.abs(new THREE.Vector3(...hit.normal_world).dot(new THREE.Vector3(...beam.direction)));
    const idealIntensity = 0.65 * Math.max(0.02, incidence) * Math.exp(-hit.range_m / 200);
    // Receiver dropout happens after the opaque hit. Never search behind it.
    if (uniform(seed, beam.beam_id, 0) < dropout) {
      beamStatus[beam.beam_id] = LIDAR_STATUS.receiver_dropout;
      continue;
    }
    const range = Math.min(sensor.max_range_m, Math.max(sensor.min_range_m,
      hit.range_m + rangeSigma * gaussian(seed, beam.beam_id, 1)));
    const sensorPoint = new THREE.Vector3(...beam.direction_sensor).multiplyScalar(range);
    // The sensor coordinate is formed from the emitted beam, not a mesh vertex.
    const worldPoint = new THREE.Vector3(...beam.origin).addScaledVector(new THREE.Vector3(...beam.direction), range);
    sensorPoint.copy(worldPoint.applyMatrix4(sensorFromWorld));
    points.push({
      xyz_sensor: sensorPoint.toArray() as Vec3,
      intensity: Math.max(0, Math.min(1, idealIntensity + intensitySigma * gaussian(seed, beam.beam_id, 3))),
      beam_id: beam.beam_id, time_offset_s: beam.time_offset_s, range_m: range,
    });
    beamStatus[beam.beam_id] = LIDAR_STATUS.surface;
  }
  return {
    version: LIDAR_MODEL_VERSION, sensor_id: sensor.sensor_id,
    rows: pattern.rows, columns: pattern.columns,
    beam_status: beamStatus, ideal_hits: idealHits, points,
    response: { range_sigma_m: rangeSigma, intensity_sigma: intensitySigma,
      dropout_probability: dropout, intensity_model: "synthetic-incidence-exponential.v1" },
  };
}
