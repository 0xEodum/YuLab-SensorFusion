import * as THREE from "three";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { Airframe } from "source-f16";
import { LIVERIES as F16_LIVERIES } from "source-f16-liveries";
import { GlobalHawk } from "source-rq4";
import { LIVERIES as RQ4_LIVERIES } from "source-rq4-liveries";
import { createVehicle } from "source-vehicle";
import { Cruiser } from "source-cruiser";
import { ShipProvider } from "source-cruiser-state";
import Destroyer from "source-destroyer";
import { A10 } from "source-a10";
import { LIVERIES as A10_LIVERIES } from "source-a10-liveries";
import { PRESETS as A10_PRESETS } from "source-a10-presets";
import { Tomcat } from "source-f14";
import { LIVERIES as F14_LIVERIES } from "source-f14-liveries";
import { PRESETS as F14_PRESETS } from "source-f14-presets";
import { Aircraft as F16XL } from "source-f16xl";
import { buildLivery as buildF16XLLivery } from "source-f16xl-liveries";
import { PRESETS as F16XL_PRESETS } from "source-f16xl-presets";
import { Hornet } from "source-f18";
import { LIVERY_MAP as F18_LIVERIES } from "source-f18-liveries";
import { F22 } from "source-f22";
import { Reaper } from "source-mq9";
import { LIVERIES as MQ9_LIVERIES } from "source-mq9-liveries";
import { PRESETS as MQ9_PRESETS } from "source-mq9-presets";
import Su35 from "source-su35";
import { LIVERIES as SU35_LIVERIES } from "source-su35-liveries";
import { PRESETS as SU35_PRESETS } from "source-su35-presets";
import { RadarVehicle as ComplexRadar } from "source-complex-radar";
import { VehicleFrame, ESR_SCHEME } from "source-simulation-frame";
import { RADARS } from "source-simulation-registry";
import { SPAAModel } from "source-spaa";
import { defaultSettings } from "source-spaa-settings";
import { Fragment, createElement } from "./static-react.mjs";

function materialize(element, parent) {
  if (element == null || typeof element === "boolean") return;
  if (Array.isArray(element)) {
    element.forEach((e) => materialize(e, parent));
    return;
  }
  const { type, props } = element;
  if (type === Fragment) return materialize(props.children, parent);
  if (typeof type === "function") return materialize(type(props), parent);
  if (typeof type === "string" && type.endsWith("Light")) return;
  if (type === "primitive") {
    if (props.object) parent.add(props.object);
    return;
  }
  const constructors = {
    group: THREE.Group,
    object3D: THREE.Object3D,
    mesh: THREE.Mesh,
    instancedMesh: THREE.Mesh,
    line: THREE.Line,
    lineSegments: THREE.LineSegments,
    meshStandardMaterial: THREE.MeshStandardMaterial,
    meshBasicMaterial: THREE.MeshBasicMaterial,
    meshPhysicalMaterial: THREE.MeshPhysicalMaterial,
    lineBasicMaterial: THREE.LineBasicMaterial,
    boxGeometry: THREE.BoxGeometry,
    torusGeometry: THREE.TorusGeometry,
    cylinderGeometry: THREE.CylinderGeometry,
    circleGeometry: THREE.CircleGeometry,
    coneGeometry: THREE.ConeGeometry,
    sphereGeometry: THREE.SphereGeometry,
    planeGeometry: THREE.PlaneGeometry,
    ringGeometry: THREE.RingGeometry,
    icosahedronGeometry: THREE.IcosahedronGeometry,
    octahedronGeometry: THREE.OctahedronGeometry,
    dodecahedronGeometry: THREE.DodecahedronGeometry,
    extrudeGeometry: THREE.ExtrudeGeometry,
    latheGeometry: THREE.LatheGeometry,
    capsuleGeometry: THREE.CapsuleGeometry,
  };
  const Constructor = constructors[type];
  if (!Constructor)
    throw new Error(`Unsupported static JSX element: ${String(type)}`);
  const object = new Constructor(...(type === "instancedMesh" ? [] : props.args ?? []));
  for (const [key, value] of Object.entries(props)) {
    if (["children", "args", "ref", "key"].includes(key) || value === undefined)
      continue;
    if (object[key]?.isColor) object[key].set(value);
    else if (["position", "rotation", "scale"].includes(key))
      typeof value === "number" ? object[key].setScalar(value) : object[key].set(...value);
    else if (key === "quaternion") object.quaternion.set(...value);
    else if (key === "rotation-x") object.rotation.x = value;
    else if (key === "rotation-y") object.rotation.y = value;
    else if (key === "rotation-z") object.rotation.z = value;
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
  const cruiser = new THREE.Group();
  materialize(createElement(ShipProvider, null, createElement(Cruiser, null)), cruiser);
  sources.push({ id: "cruiser", root: cruiser, yaw: -Math.PI / 2,
    kind: "ship", contacts: [[0, 0, 0]] });
  const destroyer = new THREE.Group();
  materialize(createElement(Destroyer, null), destroyer);
  sources.push({ id: "destroyer", root: destroyer, yaw: -Math.PI / 2,
    kind: "ship", contacts: [[0, 0, 0]] });
  const addStatic = (id, element, yaw = 0, kind = "aircraft") => {
    const root = new THREE.Group();
    materialize(element, root);
    sources.push({ id, root, yaw, kind, contacts: null });
  };
  addStatic("a10", createElement(A10, { livery: A10_LIVERIES[1],
    loadout: A10_PRESETS[0].loadout, gearDown: true, wireframe: false,
    selectedStation: null, showStations: false }));
  addStatic("f14", createElement(Tomcat, { livery: F14_LIVERIES[0],
    loadout: F14_PRESETS[0].loadout, sweep: 20, gearDown: true,
    canopyOpen: false, afterburner: false, outline: false }));
  addStatic("f16xl", createElement(F16XL, { livery: buildF16XLLivery("usaf"),
    loadout: F16XL_PRESETS[0].loadout, gearDown: true, wireframe: false,
    showLabels: false, selected: null, onSelect: () => {} }), -Math.PI / 2);
  addStatic("f18", createElement(Hornet, { livery: F18_LIVERIES.jolly,
    gearDown: true, afterburner: false, wireframe: false }));
  addStatic("f22", createElement(F22, { bayOpen: false, deployed: false,
    afterburner: false, wireframe: false }), -Math.PI / 2);
  addStatic("mq9", createElement(Reaper, { livery: MQ9_LIVERIES[0],
    loadout: MQ9_PRESETS[0].loadout, gearDown: true, propSpin: false,
    showLabels: false, selectedStation: null, onSelectStation: () => {} }));
  addStatic("su35", createElement(Su35, { livery: SU35_LIVERIES.black,
    loadout: SU35_PRESETS[0].build(), options: { wireframe: false,
      gear: true, afterburner: false, markers: false, hover: false } }));
  addStatic("complex-radar", createElement(ComplexRadar, { type: "phased",
    active: false, mastRaised: true, beams: false, showLabel: false }),
    -Math.PI / 2, "ground_vehicle");
  addStatic("simulation-radar", createElement(VehicleFrame, { scheme: ESR_SCHEME,
    children: createElement("group", { position: [0, 3.5, 0.75] },
      createElement(RADARS.pa3.Component, {})) }), 0, "ground_vehicle");
  addStatic("spaa", createElement(SPAAModel, {
    settingsRef: { current: defaultSettings } }), 0, "ground_vehicle");
  const results = [];
  for (const source of sources) {
    const originalBounds = new THREE.Box3().setFromObject(source.root, true);
    source.root.rotation.y = source.yaw;
    source.root.position.y = source.kind === "ship" ? 0 : -originalBounds.min.y;
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
      if (!node.isMesh) return;
      if (!Array.isArray(node.material)) {
        meshes.push(node);
        return;
      }
      const geometry = node.geometry.index ? node.geometry.toNonIndexed() : node.geometry;
      if (!geometry.groups.length)
        throw new Error(`${source.id}: multi-material mesh has no groups`);
      for (const group of geometry.groups) {
        const material = node.material[group.materialIndex];
        if (!material) throw new Error(`${source.id}: missing grouped material`);
        const piece = new THREE.BufferGeometry();
        for (const [key, attr] of Object.entries(geometry.attributes)) {
          const lo = group.start * attr.itemSize;
          const hi = (group.start + group.count) * attr.itemSize;
          piece.setAttribute(key, new THREE.BufferAttribute(attr.array.slice(lo, hi), attr.itemSize,
            attr.normalized));
        }
        piece.name = geometry.name;
        const split = new THREE.Mesh(piece, material);
        split.name = node.name;
        split.matrixWorld.copy(node.matrixWorld);
        meshes.push(split);
      }
    });
    for (let i = 0; i < meshes.length; i++) {
      const node = meshes[i];
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
      } else if (source.kind === "ship") {
        const center = localBounds.getCenter(new THREE.Vector3()).applyMatrix4(node.matrixWorld);
        if (center.z < -12 && center.z > -50 && center.y > 6 && center.y < 24)
          semantic = "engine-surface";
        if (center.z < -12 && center.z > -50 && center.y >= 24)
          semantic = "exhaust-surface";
      } else if (source.kind === "aircraft") {
        const center = localBounds.getCenter(new THREE.Vector3()).applyMatrix4(node.matrixWorld);
        if (center.z < -Math.max(2.5, originalBounds.getSize(new THREE.Vector3()).length() * 0.13)
            && center.y > 0.4)
          semantic = "engine-surface";
      } else if (source.kind === "ground_vehicle") {
        const center = localBounds.getCenter(new THREE.Vector3()).applyMatrix4(node.matrixWorld);
        if (center.z > 1.8 && center.y < 3) semantic = "engine-surface";
        if (center.z < -2.5 && center.y < 3) semantic = "radiator-surface";
      } else {
        // Authored vehicle has no exhaust model: name front engine-cover and rear radiator surfaces.
        const center = localBounds
          .getCenter(new THREE.Vector3())
          .applyMatrix4(node.matrixWorld);
        if (center.z > 4.7 && center.y < 2.8) semantic = "engine-surface";
        if (center.z < -5.3 && center.y > 1.2 && center.y < 2.5)
          semantic = "radiator-surface";
      }
      const thermalProfiles = {
        "body-surface": [0.82, 0.55, 250000, 4, 8],
        "engine-surface": [0.88, 0.65, 120000, 2, 12],
        "exhaust-surface": [0.92, 0.7, 60000, 1, 20],
        "radiator-surface": [0.94, 0.75, 100000, 1.5, 16],
      };
      const materialKey = `${node.material.uuid}:${semantic}`;
      if (!materialIds.has(materialKey)) {
        const id = `material-${materials.length}`;
        materialIds.set(materialKey, id);
        const [emissivity, solar_absorption, thermal_capacity_j_per_k,
          area_m2, convection_w_per_m2_k] = thermalProfiles[semantic];
        materials.push({
          id,
          emissivity,
          solar_absorption,
          thermal_capacity_j_per_k,
          area_m2,
          convection_w_per_m2_k,
          response_time_s: thermal_capacity_j_per_k /
            (convection_w_per_m2_k * area_m2),
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
        material_id: materialIds.get(materialKey),
        semantic,
      });
    }
    const bounds = new THREE.Box3().setFromObject(out, true);
    // Choose real tread vertices near each authored wheel; polygonal tyres need not
    // reach the analytic cylinder radius. Keep any inter-wheel height residual visible.
    const autoContacts = () => {
      const vertices = [];
      for (const mesh of out.children) {
        const positions = mesh.geometry.attributes.position;
        for (let j = 0; j < positions.count; j++) {
          const v = new THREE.Vector3().fromBufferAttribute(positions, j);
          if (v.y < bounds.min.y + 0.08) vertices.push(v);
        }
      }
      if (!vertices.length) throw new Error(`${source.id}: no ground support vertices`);
      const unique = new Map(vertices.map((v) => [`${v.x.toFixed(3)},${v.z.toFixed(3)}`, v]));
      const points = [...unique.values()].sort((a, b) => a.x - b.x);
      const pick = [points[0], points.at(-1),
        [...points].sort((a, b) => a.z - b.z).at(-1)];
      return pick.map((v) => v.toArray());
    };
    const contacts = (source.contacts ?? autoContacts()).map((p) => {
      if (!source.contacts) return p;
      if (source.kind === "ship") return [...p];
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
        ...(source.kind === "ship" ? { waterline_m: 0 } : {}),
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
        frozen_pose: source.kind === "ship"
          ? "At rest at authored waterline; no source animations, projectiles or app"
          : source.id === "f22"
            ? "Static flight pose; source has no landing gear, so this model is catalog-only and not parked on the airfield"
            : "Parked grounded pose; engine off; no frame callbacks, stores, projectiles or source app",
        scale_basis:
          "Authored metre-scale geometry, uniform scale 1; source proportions including probes preserved. Not a certified real-aircraft dimensional model.",
        thermal_policy:
          "Named opaque exterior surface nodes use thermal-surface.v1 synthetic coefficients. Interior power couples to engine, exhaust and radiator surfaces; source geometry is not directly visible.",
      },
    });
  }
  return results;
};
