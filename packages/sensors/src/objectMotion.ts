import * as THREE from "three";
import type { AssetRecord, WorldSpec, TemporalCapture } from "@yulab/contracts";
import { validatePayload } from "@yulab/contracts/validate";
import { buildLidarScene, type LidarGeometryCache, type LidarHit } from "./lidar.ts";

type Transform = WorldSpec["instances"][number]["T_world_from_asset"];
type Vec3 = [number, number, number];
const matrix = (v: readonly number[]) => new THREE.Matrix4().set(...v as Parameters<THREE.Matrix4["set"]>);
const rowMajor = (m: THREE.Matrix4) => m.clone().transpose().toArray() as Transform;

/** World instance poses are reference_time_s snapshots. Object motion is truth,
 * evaluated at absolute capture time plus sample offset, never a model input. */
export function objectMotionSampler(world: WorldSpec, state: TemporalCapture, captureTime: number) {
  validatePayload("WorldSpec", world); validatePayload("TemporalCapture", state);
  if (!Number.isFinite(captureTime) || captureTime < 0) throw new Error("Invalid capture time");
  const base = structuredClone(world), description = structuredClone(state);
  const motions = new Map((description.object_motion ?? []).map(m => [m.instance_id, m]));
  if (motions.size !== (description.object_motion ?? []).length) throw new Error("Duplicate object trajectory");
  const instances = new Map(base.instances.map(i => [i.instance_id, i]));
  for (const id of motions.keys()) {
    const instance = instances.get(id);
    if (!instance) throw new Error(`Unknown moving instance: ${id}`);
    const m = matrix(instance.T_world_from_asset), p = new THREE.Vector3(), q = new THREE.Quaternion(), scale = new THREE.Vector3();
    m.decompose(p,q,scale);
    const reconstructed = new THREE.Matrix4().compose(p,q,new THREE.Vector3(1,1,1));
    if (m.elements.some((v,i)=>Math.abs(v-reconstructed.elements[i])>1e-6))
      throw new Error("Moving objects require rigid instance transforms");
  }
  const at = (id: string, offset: number) => {
    if (!Number.isFinite(offset) || captureTime + offset < 0) throw new Error("Invalid object sample time");
    const instance=instances.get(id);
    if (!instance) throw new Error(`Unknown instance: ${id}`);
    const m=matrix(instance.T_world_from_asset), motion=motions.get(id);
    if (!motion) return m;
    const dt=captureTime+offset-description.reference_time_s;
    const p=new THREE.Vector3().setFromMatrixPosition(m);
    m.setPosition(0,0,0).premultiply(new THREE.Matrix4().makeRotationY(motion.yaw_rate_rad_per_s*dt));
    return m.setPosition(p.addScaledVector(new THREE.Vector3(...motion.velocity_world_m_per_s),dt));
  };
  const activeIds=[...motions].filter(([,m])=>m.yaw_rate_rad_per_s!==0 || m.velocity_world_m_per_s.some(v=>v!==0)).map(([id])=>id).sort();
  const inverseAnchors=new Map(activeIds.map(id=>[id,at(id,0).invert()]));
  return {
    activeIds,
    worldAt(offset: number): WorldSpec {
      const result=structuredClone(base);
      for (const instance of result.instances) instance.T_world_from_asset=rowMajor(at(instance.instance_id,offset));
      return result;
    },
    apply(scene: THREE.Object3D, offset: number) {
      scene.updateMatrixWorld(true);
      for (const id of activeIds) {
        const object=scene.getObjectByName(id);
        if (!object) throw new Error(`Missing moving scene instance: ${id}`);
        object.matrixAutoUpdate=false;
        object.matrix.copy(at(id,offset));
        if (object.parent) object.matrix.premultiply(object.parent.matrixWorld.clone().invert());
        object.updateMatrixWorld(true);
      }
    },
    delta(id: string, offset: number) {
      const inverse=inverseAnchors.get(id);
      if (!inverse) throw new Error("Unknown active trajectory");
      return at(id,offset).multiply(inverse);
    },
  };
}

/** Static BVH plus one immutable BVH per moving instance. Transform a beam to
 * each object's anchor-world frame; transform its hit/normal back. No per-beam
 * triangle BVH rebuild. Static geometry wins exact ties, then sorted instance ID. */
export function buildMovingLidarScene(root: THREE.Object3D, catalog: readonly AssetRecord[],
  cache: LidarGeometryCache | null, motion: ReturnType<typeof objectMotionSampler>) {
  if (!motion.activeIds.length) return buildLidarScene(root,catalog,cache);
  const ids=new Set(motion.activeIds);
  const fixed=buildLidarScene(root,catalog,cache,id=>id===null || !ids.has(id));
  const moving: {id: string; scene: ReturnType<typeof buildLidarScene>}[]=[];
  try {
    for (const id of motion.activeIds) {
      const object=root.getObjectByName(id);
      if (!object) throw new Error(`Missing moving instance: ${id}`);
      moving.push({id,scene:buildLidarScene(object,catalog,cache)});
    }
  } catch (error) {
    fixed.dispose(); moving.forEach(m=>m.scene.dispose()); throw error;
  }
  return {
    mesh_count: fixed.mesh_count+moving.reduce((n,m)=>n+m.scene.mesh_count,0),
    triangle_count: fixed.triangle_count+moving.reduce((n,m)=>n+m.scene.triangle_count,0),
    first(origin: Vec3, direction: Vec3, near: number, far: number, offset=0): LidarHit | null {
      let best=fixed.first(origin,direction,near,far);
      for (const {id,scene} of moving) {
        const delta=motion.delta(id,offset), inverse=delta.clone().invert();
        const o=new THREE.Vector3(...origin).applyMatrix4(inverse).toArray() as Vec3;
        const d=new THREE.Vector3(...direction).transformDirection(inverse).toArray() as Vec3;
        const hit=scene.first(o,d,near,far);
        if (!hit || (best && hit.range_m>=best.range_m-1e-9)) continue;
        best={...hit, point_world:new THREE.Vector3(...hit.point_world).applyMatrix4(delta).toArray() as Vec3,
          normal_world:new THREE.Vector3(...hit.normal_world).transformDirection(delta).toArray() as Vec3};
      }
      return best;
    },
    dispose() { fixed.dispose(); moving.forEach(m=>m.scene.dispose()); },
  };
}
