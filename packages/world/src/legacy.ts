import { noise } from './noise.ts';
import * as THREE from 'three';
import { MarchingCubes } from 'three/addons/objects/MarchingCubes.js';

export type TerrainConfig = {
  seed: number; scale: number; height: number; roughness: number; detail: number;
  arches: boolean; overhangs: boolean; tunnels: boolean; strength: number;
  preset: string; palette: string; vegetation: boolean; water: boolean;
};
export const DEFAULT_CONFIG: TerrainConfig = { seed: 48291, scale: 64, height: 42, roughness: 55, detail: 48, arches: true, overhangs: true, tunnels: true, strength: 65, preset: 'canyon', palette: 'earth', vegetation: true, water: false };
export const PRESETS = [
  { id: 'canyon', name: 'Canyon arches', description: 'Sculpted by time', config: { ...DEFAULT_CONFIG } },
  { id: 'alpine', name: 'Alpine peaks', description: 'A little closer to the sky', config: { ...DEFAULT_CONFIG, preset: 'alpine', seed: 81327, height: 68, roughness: 70, arches: false, palette: 'alpine' } },
  { id: 'islands', name: 'Floating islands', description: 'Beyond the ordinary', config: { ...DEFAULT_CONFIG, preset: 'islands', seed: 26018, height: 50, palette: 'moss', arches: true } },
  { id: 'coast', name: 'Coastal cliffs', description: 'Where land meets sea', config: { ...DEFAULT_CONFIG, preset: 'coast', seed: 71042, height: 38, arches: true, water: true, palette: 'coast' } },
];

function randomGenerator(seed: number) { return () => { seed = (Math.imul(1664525, seed) + 1013904223) | 0; return (seed >>> 0) / 4294967296; }; }

export function createTerrain(config: TerrainConfig, preview = false) {
  const group = new THREE.Group();
  group.name = 'Strata terrain';
  const res = preview ? 43 : Math.round(38 + config.detail * .31);
  const material = new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 1, metalness: 0 });
  const mc = new MarchingCubes(res, material, false, false, 90000);
  mc.isolation = 0;
  const h = .65 + config.height / 100;
  const rough = config.roughness / 100;
  const strength = config.strength / 100;
  const seed = config.seed;
  const landscapeScale = .82 + config.scale / 350;
  const density = (xx: number, yy: number, zz: number) => {
    const x = xx / landscapeScale, y = yy / h, z = zz / landscapeScale;
    const n = noise(x * .55, y * .6, z * .55, seed) * rough * .95 + noise(x * 1.4, y * 1.3, z * 1.4, seed + 9) * rough * .23;
    const edge = 1 - (x * x / 105 + z * z / 68);
    const groundHeight = 1.35 + noise(x * .25, 0, z * .25, seed) * .8 + noise(x * .7, 0, z * .7, seed) * rough * .7;
    let ground = Math.min(groundHeight - y, (edge + n * .09) * 6, y + 1.6 + noise(x * .5, 0, z * .5, seed) * .3);
    const ellipsoid = (cx: number, cy: number, cz: number, rx: number, ry: number, rz: number) => (1 - Math.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 + ((z - cz) / rz) ** 2)) * Math.min(rx, ry, rz);
    let rock: number;
    if (config.preset === 'alpine') {
      rock = Math.max(ellipsoid(-3.3, 2.2, -1.3, 4.3, 7.4, 4), ellipsoid(3, 1, -2.3, 4.8, 6, 3.7), ellipsoid(-.5, 1, 2.6, 3.2, 4, 2.8)) + n * 1.5;
    } else if (config.preset === 'islands') {
      ground = -100;
      rock = Math.max(ellipsoid(-4.8, 2.4, .8, 4.6, 3, 4.1), ellipsoid(3.6, 5.3, -1.6, 4.5, 3.1, 3.6), ellipsoid(4.9, .1, 4.7, 2.6, 2.1, 2.5), ellipsoid(-4.8, 5.4, .4, 2.2, 2.6, 2)) + n * .9;
      if (config.arches) rock = Math.min(rock, (Math.sqrt(((x - 3.6) / 1.9) ** 2 + ((y - 4.6) / 1.5) ** 2) - 1) * 1.5);
    } else {
      // An extruded, noise-warped elliptical rock mass. Subtracting a full
      // 3D cylinder creates a real through-opening, including its underside.
      const outer = (1 - Math.sqrt((x / 6.5) ** 2 + ((y - 2.7) / 6.15) ** 2)) * 4.5;
      const thickness = 1.75 + noise(x * .35, y * .3, 0, seed + 2) * .8 + (config.overhangs ? strength * Math.max(0, y - 4) * .19 : 0);
      let arch = Math.min(outer, thickness - Math.abs(z + .65 + x * .055)) + n;
      if (config.arches) {
        const opening = (Math.sqrt(((x + .35) / (2.65 + strength * 1.1)) ** 2 + ((y - 2.2) / (3.6 + strength * .8)) ** 2) - 1) * 3.4;
        arch = Math.min(arch, opening + n * .3);
      }
      rock = Math.max(arch, ellipsoid(-5.6, 2, -1.3, 3.4, 4.9, 3.2) + n, ellipsoid(5.5, 1.1, -.5, 3.3, 3.7, 3.5) + n, ellipsoid(-6.4, 1, 3.1, 2.4, 2.5, 2.3) + n);
      if (config.overhangs) {
        rock = Math.max(rock, ellipsoid(5.5, 3.6, 1, 3.1, .85 + strength * .4, 2.9) + n * .7);
      }
      if (config.tunnels) {
        const tunnel = Math.sqrt(((x - 5.4) / 1.15) ** 2 + ((y - 1.9) / 1.3) ** 2) - 1;
        rock = Math.min(rock, tunnel + n * .12);
      }
      if (config.preset === 'coast') ground = Math.min(ground, x + 6.7 + Math.sin(z * .5) * 1.2);
    }
    return Math.max(ground, rock);
  };
  for (let k = 0; k < res; k++) for (let j = 0; j < res; j++) for (let i = 0; i < res; i++) {
    const x = (i / res * 2 - 1) * 13;
    const y = (j / res * 2 - 1) * 13 + 5;
    const z = (k / res * 2 - 1) * 13;
    mc.field[i + j * res + k * res * res] = density(x, y, z);
  }
  mc.update();
  const count = mc.geometry.drawRange.count;
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array((mc.geometry.getAttribute('position').array as Float32Array).slice(0, count * 3));
  for (let i = 0; i < positions.length; i += 3) { positions[i] *= 13; positions[i + 1] = positions[i + 1] * 13 + 5; positions[i + 2] *= 13; }
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  const normals = geometry.getAttribute('normal');
  const colors = new Float32Array(positions.length);
  const palettes: Record<string, { rock: string; grass: string; deep: string }> = {
    earth: { rock: '#bf9870', grass: '#7e8b54', deep: '#8e6849' },
    alpine: { rock: '#9da5a0', grass: '#7d916b', deep: '#606e69' },
    moss: { rock: '#9b9b7e', grass: '#728f68', deep: '#6a7160' },
    coast: { rock: '#c3b294', grass: '#8eaa7c', deep: '#877967' },
    desert: { rock: '#d49369', grass: '#bca36e', deep: '#a15f42' },
  };
  const palette = palettes[config.palette] || palettes.earth;
  const rng = randomGenerator(seed);
  const color = new THREE.Color();
  for (let i = 0; i < count; i += 3) {
    const x = (positions[i * 3] + positions[(i + 1) * 3] + positions[(i + 2) * 3]) / 3;
    const y = (positions[i * 3 + 1] + positions[(i + 1) * 3 + 1] + positions[(i + 2) * 3 + 1]) / 3;
    const z = (positions[i * 3 + 2] + positions[(i + 1) * 3 + 2] + positions[(i + 2) * 3 + 2]) / 3;
    const up = normals.getY(i);
    const path = Math.abs(x - Math.sin(z * .45) * 1.1) < 1.15 && z > .2 && y < 2.2;
    const grass = up > .62 && y > .7 && !path && noise(x * .35, y * .1, z * .35, seed + 4) > -.48;
    color.set(grass ? palette.grass : y < -.1 ? palette.deep : palette.rock);
    if (config.palette === 'alpine' && y > 7.5 && up > .35) color.set('#e9e9dc');
    const strata = !grass && y > 0 ? Math.sin(y * 3.4 + .2 * x) * .055 : 0;
    color.multiplyScalar(.91 + rng() * .18 + strata);
    for (let v = 0; v < 3; v++) { colors[(i + v) * 3] = color.r; colors[(i + v) * 3 + 1] = color.g; colors[(i + v) * 3 + 2] = color.b; }
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.computeBoundingSphere();
  const terrain = new THREE.Mesh(geometry, material);
  terrain.name = 'Volumetric terrain'; terrain.castShadow = true; terrain.receiveShadow = true;
  group.add(terrain);
  mc.geometry.dispose();

  const raycaster = new THREE.Raycaster();
  const treeMaterials = ['#3e5640', '#4c6446', '#617451', '#73805a'].map(c => new THREE.MeshStandardMaterial({ color: c, flatShading: true, roughness: 1 }));
  const trunkMaterial = new THREE.MeshStandardMaterial({ color: '#66543c', roughness: 1 });
  const vegetation = new THREE.Group(); vegetation.name = 'Vegetation';
  if (config.vegetation) {
    for (let i = 0; i < 145; i++) {
      const x = (rng() - .5) * 19, z = (rng() - .5) * 14;
      if (Math.abs(x) < 3.5 && z > -2) continue;
      raycaster.set(new THREE.Vector3(x, 20, z), new THREE.Vector3(0, -1, 0));
      const hit = raycaster.intersectObject(terrain)[0];
      if (!hit || hit.point.y < .8 || hit.point.y > 7.5 * h || (hit.face?.normal.y || 0) < .65) continue;
      const tree = new THREE.Group();
      const size = .6 + rng() * .75;
      const trunk = new THREE.Mesh(new THREE.CylinderGeometry(.065, .085, size * .7, 5), trunkMaterial); trunk.position.y = size * .35; tree.add(trunk);
      for (let layer = 0; layer < 3; layer++) {
        const cone = new THREE.Mesh(new THREE.ConeGeometry(size * (.43 - layer * .09), size * .88, 5), treeMaterials[Math.floor(rng() * treeMaterials.length)]);
        cone.position.y = size * (.7 + layer * .3); cone.rotation.y = rng(); cone.castShadow = true; tree.add(cone);
      }
      tree.position.copy(hit.point); tree.rotation.y = rng() * Math.PI; vegetation.add(tree);
      if (vegetation.children.length > 46) break;
    }
  }
  group.add(vegetation);
  const rocks = new THREE.Group(); rocks.name = 'Scattered rocks';
  const rockMat = new THREE.MeshStandardMaterial({ color: palette.rock, roughness: 1, flatShading: true });
  for (let i = 0; i < 28; i++) {
    const x = (rng() - .5) * 19, z = (rng() - .5) * 13;
    raycaster.set(new THREE.Vector3(x, 17, z), new THREE.Vector3(0, -1, 0));
    const hit = raycaster.intersectObject(terrain)[0];
    if (!hit || hit.point.y < .4 || hit.point.y > 4 || (hit.face?.normal.y || 0) < .7) continue;
    const rock = new THREE.Mesh(new THREE.DodecahedronGeometry(.15 + rng() * .35, 0), rockMat);
    rock.position.copy(hit.point); rock.rotation.set(rng(), rng(), rng()); rock.scale.set(1.3, .7, 1); rock.castShadow = true; rocks.add(rock);
  }
  group.add(rocks);
  if (config.water) {
    const water = new THREE.Mesh(new THREE.CylinderGeometry(10.3, 10.3, .32, 12), new THREE.MeshStandardMaterial({ color: '#8dbab5', flatShading: true, transparent: true, opacity: .83, roughness: .35 }));
    water.name = 'Water'; water.position.y = -.15; water.scale.z = .79; water.receiveShadow = true; group.add(water);
  }
  return { group, triangles: count / 3, vertices: count, resolution: res };
}

export function disposeGroup(group: THREE.Object3D) {
  const materials = new Set<THREE.Material>();
  group.traverse(obj => { if (obj instanceof THREE.Mesh) { obj.geometry.dispose(); (Array.isArray(obj.material) ? obj.material : [obj.material]).forEach(m => materials.add(m)); } });
  materials.forEach(m => m.dispose());
}

export function setupScene() {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#eeeae2');
  const ambient = new THREE.HemisphereLight('#fff9e9', '#9c9580', 2.4); scene.add(ambient);
  const sun = new THREE.DirectionalLight('#fff3db', 3.1); sun.position.set(-12, 22, 15); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); sun.shadow.camera.left = -18; sun.shadow.camera.right = 18; sun.shadow.camera.top = 18; sun.shadow.camera.bottom = -18;
  sun.shadow.normalBias = .08; sun.shadow.bias = -.0001; sun.shadow.radius = 4; scene.add(sun);
  const fill = new THREE.DirectionalLight('#e8f0ef', .8); fill.position.set(10, 7, -10); scene.add(fill);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.ShadowMaterial({ color: '#514838', opacity: .13 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -2.9; floor.receiveShadow = true; scene.add(floor);
  return scene;
}

export function makePreviews() {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
  renderer.setSize(400, 210); renderer.setPixelRatio(1); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15;
  const scene = setupScene();
  const camera = new THREE.PerspectiveCamera(30, 400 / 210, .1, 200);
  camera.position.set(18, 12, 24); camera.lookAt(0, 2.7, 0);
  const previews: Record<string, string> = {};
  for (const preset of PRESETS) {
    const { group } = createTerrain(preset.config, true); scene.add(group); renderer.render(scene, camera);
    previews[preset.id] = renderer.domElement.toDataURL('image/png');
    scene.remove(group); disposeGroup(group);
  }
  disposeGroup(scene); renderer.dispose(); renderer.forceContextLoss();
  return previews;
}
