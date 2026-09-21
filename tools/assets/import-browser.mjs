import * as THREE from "three";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { Airframe } from "source-f16";
import { LIVERIES as F16_LIVERIES } from "source-f16-liveries";
import { GlobalHawk } from "source-rq4";
import { LIVERIES as RQ4_LIVERIES } from "source-rq4-liveries";
import { createVehicle } from "source-vehicle";
import { Fragment } from "./static-react.mjs";

function materialize(element, parent) {
  if (element == null || typeof element === "boolean") return;
  if (Array.isArray(element)) {
    element.forEach((e) => materialize(e, parent));
    return;
  }
  const { type, props } = element;
  if (type === Fragment) return materialize(props.children, parent);
  if (typeof type === "function") return materialize(type(props), parent);
  const constructors = {
    group: THREE.Group,
    mesh: THREE.Mesh,
    meshStandardMaterial: THREE.MeshStandardMaterial,
    boxGeometry: THREE.BoxGeometry,
    torusGeometry: THREE.TorusGeometry,
    cylinderGeometry: THREE.CylinderGeometry,
    circleGeometry: THREE.CircleGeometry,
    coneGeometry: THREE.ConeGeometry,
    sphereGeometry: THREE.SphereGeometry,
  };
  const Constructor = constructors[type];
  if (!Constructor)
    throw new Error(`Unsupported static JSX element: ${String(type)}`);
  const object = new Constructor(...(props.args ?? []));
  for (const [key, value] of Object.entries(props)) {
    if (["children", "args", "ref", "key"].includes(key) || value === undefined)
      continue;
    if (object[key]?.isColor) object[key].set(value);
    else if (["position", "rotation", "scale"].includes(key))
      object[key].set(...value);
    else object[key] = value;
  }
  if (object.isMaterial) parent.material = object;
  else if (object.isBufferGeometry) parent.geometry = object;
  else parent.add(object);
  materialize(props.children, object);
}

function reverseWinding(geometry, invertNormals = false) {
  // Non-indexed export makes reflected transforms explicit to every future consumer.
  for (const attr of Object.values(geometry.attributes)) {
    for (let i = 0; i < attr.count; i += 3)
      for (let c = 0; c < attr.itemSize; c++) {
        const a = (i + 1) * attr.itemSize + c,
          b = (i + 2) * attr.itemSize + c;
        [attr.array[a], attr.array[b]] = [attr.array[b], attr.array[a]];
      }
  }
  if (invertNormals) {
    const n = geometry.attributes.normal;
    for (let i = 0; i < n.array.length; i++) n.array[i] *= -1;
  }
}

const sha = async (bytes) =>
  Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)))
    .map((n) => n.toString(16).padStart(2, "0"))
    .join("");

window.importAssets = async () => {
  // Freeze the import-only random stream, including library-generated identities.
  let paintSeed = 0x53463034;
  Math.random = () => {
    paintSeed = (Math.imul(paintSeed, 1664525) + 1013904223) >>> 0;
    return paintSeed / 4294967296;
  };
  const sources = [];
  const f16 = new THREE.Group();
  materialize(
    Airframe({ livery: F16_LIVERIES[0], gearDown: true, afterburner: false }),
    f16,
  );
  sources.push({
    id: "f16",
    root: f16,
    yaw: -Math.PI / 2,
    contacts: [
      [2.55, -2.2, 0],
      [-1, -2.2, 1.3],
      [-1, -2.2, -1.3],
    ],
  });
  const rq4 = new THREE.Group();
  materialize(
    GlobalHawk({
      livery: RQ4_LIVERIES[0],
      wireframe: false,
      gearDown: true,
      motion: false,
    }),
    rq4,
  );
  sources.push({
    id: "rq4",
    root: rq4,
    yaw: 0,
    contacts: [
      [0, -1.9, 5],
      [1.75, -1.9, -0.9],
      [-1.75, -1.9, -0.9],
    ],
  });
  sources.push({
    id: "ground-vehicle",
    root: createVehicle().vehicle,
    yaw: Math.PI / 2,
    contacts: [-3.45, -1.35, 1.5, 3.65].flatMap((x) =>
      [-1.47, 1.47].map((z) => [x, 0, z]),
    ),
  });
  const results = [];
  for (const source of sources) {
    const originalBounds = new THREE.Box3().setFromObject(source.root, true);
    source.root.rotation.y = source.yaw;
    source.root.position.y = -originalBounds.min.y;
    source.root.updateMatrixWorld(true);
    const out = new THREE.Group();
    out.name = source.id;
    const parts = [],
      materials = [],
      materialIds = new Map(),
      meshes = [],
      exportedMaterials = new Map();
    let maxNormalError = 0,
      triangles = 0;
    source.root.traverse((node) => {
      if (node.isMesh) meshes.push(node);
    });
    for (let i = 0; i < meshes.length; i++) {
      const node = meshes[i];
      if (Array.isArray(node.material))
        throw new Error("Multi-material source mesh needs an explicit adapter");
      let geo = node.geometry.index
        ? node.geometry.toNonIndexed()
        : node.geometry.clone();
      const localBounds = new THREE.Box3().setFromBufferAttribute(
        node.geometry.attributes.position,
      );
      geo.applyMatrix4(node.matrixWorld);
      if (node.matrixWorld.determinant() < 0) reverseWinding(geo);
      if (!exportedMaterials.has(node.material.uuid))
        exportedMaterials.set(node.material.uuid, node.material.clone());
      const material = exportedMaterials.get(node.material.uuid);
      if (node.material.side === THREE.BackSide) {
        reverseWinding(geo, true);
        material.side = THREE.FrontSide;
      }
      // Source flat shading is a material flag, absent from glTF; bake it into normals.
      if (material.flatShading) geo.computeVertexNormals();
      const normals = geo.attributes.normal,
        positions = geo.attributes.position;
      for (let j = 0; j < positions.count; j++) {
        if (
          ![positions.getX(j), positions.getY(j), positions.getZ(j)].every(
            Number.isFinite,
          )
        )
          throw new Error(`${source.id}: nonfinite position`);
        const length = Math.hypot(
          normals.getX(j),
          normals.getY(j),
          normals.getZ(j),
        );
        // Degenerate source triangles have zero area and no meaningful normal. Remove below.
        if (length > 1e-7)
          maxNormalError = Math.max(maxNormalError, Math.abs(1 - length));
      }
      const keep = [];
      const a = new THREE.Vector3(),
        b = new THREE.Vector3(),
        c = new THREE.Vector3();
      for (let j = 0; j < positions.count; j += 3) {
        a.fromBufferAttribute(positions, j);
        b.fromBufferAttribute(positions, j + 1);
        c.fromBufferAttribute(positions, j + 2);
        if (b.sub(a).cross(c.sub(a)).lengthSq() > 1e-18)
          keep.push(j, j + 1, j + 2);
      }
      if (keep.length !== positions.count) {
        const clean = new THREE.BufferGeometry();
        for (const [key, attr] of Object.entries(geo.attributes)) {
          const values = new Float32Array(keep.length * attr.itemSize);
          keep.forEach((old, j) => {
            for (let k = 0; k < attr.itemSize; k++)
              values[j * attr.itemSize + k] =
                attr.array[old * attr.itemSize + k];
          });
          clean.setAttribute(
            key,
            new THREE.BufferAttribute(values, attr.itemSize),
          );
        }
        geo = clean;
      }
      triangles += geo.attributes.position.count / 3;
      const label = node.geometry.name || node.name || "surface";
      let semantic = "body-surface";
      if (source.id === "f16") {
        if (label === "rear") semantic = "engine-surface";
        if (label.startsWith("nozzle")) semantic = "exhaust-surface";
      } else if (source.id === "rq4") {
        if (label === "nacelle") semantic = "engine-surface";
        if (Math.abs(node.position.z + 5.15) < 0.001)
          semantic = "exhaust-surface";
      } else {
        // Authored vehicle has no exhaust model: name front engine-cover and rear radiator surfaces.
        const center = localBounds
          .getCenter(new THREE.Vector3())
          .applyMatrix4(node.matrixWorld);
        if (center.z > 4.7 && center.y < 2.8) semantic = "engine-surface";
        if (center.z < -5.3 && center.y > 1.2 && center.y < 2.5)
          semantic = "radiator-surface";
      }
      if (!materialIds.has(node.material.uuid)) {
        const id = `material-${materials.length}`;
        materialIds.set(node.material.uuid, id);
        materials.push({
          id,
          emissivity: 0.9,
          solar_absorption: 0.6,
          thermal_capacity_j_per_k: 1000,
          area_m2: 1,
          convection_w_per_m2_k: 10,
          response_time_s: 100,
          opaque_rgb: !material.transparent,
          opaque_ir: true,
          opaque_lidar: true,
        });
      }
      const id = `part-${String(i).padStart(4, "0")}`;
      const mesh = new THREE.Mesh(geo, material);
      mesh.name = id;
      mesh.userData = { semantic, source_label: label };
      out.add(mesh);
      parts.push({
        id,
        mesh_node: id,
        material_id: materialIds.get(node.material.uuid),
        semantic,
      });
    }
    const bounds = new THREE.Box3().setFromObject(out, true);
    // Choose real tread vertices near each authored wheel; polygonal tyres need not
    // reach the analytic cylinder radius. Keep any inter-wheel height residual visible.
    const contacts = source.contacts.map((p) => {
      if (source.id === "ground-vehicle") p[1] = originalBounds.min.y;
      const ideal = new THREE.Vector3(...p).applyMatrix4(
        source.root.matrixWorld,
      );
      let lowest = null;
      for (const mesh of out.children) {
        const positions = mesh.geometry.attributes.position;
        for (let j = 0; j < positions.count; j++) {
          const v = new THREE.Vector3().fromBufferAttribute(positions, j);
          if (
            Math.hypot(v.x - ideal.x, v.z - ideal.z) < 0.4 &&
            (!lowest || v.y < lowest.y)
          )
            lowest = v;
        }
      }
      if (!lowest || Math.abs(lowest.y) > 0.015)
        throw new Error(`${source.id}: unsupported wheel contact`);
      return lowest.toArray();
    });
    const glb = await new GLTFExporter().parseAsync(out, {
      binary: true,
      onlyVisible: true,
    });
    let binary = "";
    const bytes = new Uint8Array(glb);
    for (let i = 0; i < bytes.length; i += 8192)
      binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    results.push({
      id: source.id,
      glb: btoa(binary),
      sha256: await sha(glb),
      parts,
      materials,
      bounds: {
        frame: "east-up-south",
        center_m: bounds.getCenter(new THREE.Vector3()).toArray(),
        extent_m: bounds.getSize(new THREE.Vector3()).toArray(),
        quaternion_xyzw: [0, 0, 0, 1],
      },
      metadata: {
        version: "asset-import.v1",
        axes: "+X left, +Y up, +Z forward",
        source_yaw_rad: source.yaw,
        source_ground_y: originalBounds.min.y,
        scale_m_per_source_unit: 1,
        contacts_m: contacts,
        bounds_min_m: bounds.min.toArray(),
        bounds_max_m: bounds.max.toArray(),
        source_bounds_m: {
          min: originalBounds.min.toArray(),
          max: originalBounds.max.toArray(),
        },
        validation: {
          triangles,
          meshes: parts.length,
          max_normal_error: maxNormalError,
        },
        frozen_pose:
          "gear down; engine off; no frame callbacks, stores, projectiles or source app",
        scale_basis:
          "Authored metre-scale geometry, uniform scale 1; source proportions including probes preserved. Not a certified real-aircraft dimensional model.",
        thermal_policy:
          "Named exterior regions only; synthetic placeholder material coefficients, all sources off. Thermal evolution is SF-06.",
      },
    });
  }
  return results;
};
