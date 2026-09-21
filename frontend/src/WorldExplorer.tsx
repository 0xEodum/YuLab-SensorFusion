import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  createWorld,
  defaultWorldSpec,
  meshChunk,
  chunkPlacements,
} from '@yulab/world';
import { disposeGroup } from './terrain';
import './world.css';

const featureNames = {
  canyon: 'Canyon arch',
  alpine: 'Alpine ridge',
  islands: 'Highland outcrops',
  coast: 'Coastal bluff',
  aerodrome: 'Aerodrome',
  harbor: 'Harbor',
} as const;

export default function WorldExplorer() {
  const host = useRef<HTMLDivElement>(null);
  const [seed, setSeed] = useState(0);
  const [draftSeed, setDraftSeed] = useState('0');
  const [location, setLocation] = useState(0);
  const [boundaries, setBoundaries] = useState(false);
  const [view, setView] = useState('oblique');
  const [error, setError] = useState('');
  const [stats, setStats] = useState({
    triangles: 0,
    rocks: 0,
    trees: 0,
    milliseconds: 0,
  });
  const spec = useMemo(() => defaultWorldSpec(seed), [seed]);
  const locations = useMemo(
    () =>
      spec.features.map((feature, index) => ({
        id: feature.id,
        name: `${featureNames[feature.type]} ${index + 1}`,
        type: feature.type,
        x: feature.center_m[0],
        y: feature.center_m[1],
        z: feature.center_m[2],
        extent: feature.extent_m,
      })),
    [spec],
  );
  const center = locations[location] ?? locations[0];
  const centerChunk = {
    x: Math.floor(center.x / 128),
    z: Math.floor(center.z / 128),
  };
  const engine = useRef<{
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    seams: THREE.LineSegments;
  } | null>(null);

  useEffect(() => {
    const mount = host.current;
    if (!mount) return;
    const start = performance.now();
    let renderer: THREE.WebGLRenderer | undefined;
    let observer: ResizeObserver | undefined;
    let controls: OrbitControls | undefined;
    let frame = 0;
    const scene = new THREE.Scene();
    setError('');
    try {
      const world = createWorld(spec);
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        preserveDrawingBuffer: true,
      });
      renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.2;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      mount.appendChild(renderer.domElement);
      scene.background = new THREE.Color('#e7e9e4');
      scene.add(new THREE.HemisphereLight('#f9f4e4', '#626856', 2));
      const sun = new THREE.DirectionalLight('#fff0d5', 3);
      sun.position.set(center.x - 180, 250, center.z + 170);
      sun.target.position.set(center.x, center.y, center.z);
      sun.castShadow = true;
      Object.assign(sun.shadow.camera, {
        left: -260,
        right: 260,
        top: 260,
        bottom: -260,
        near: 1,
        far: 500,
      });
      sun.shadow.mapSize.set(2048, 2048);
      sun.shadow.normalBias = 0.2;
      scene.add(sun, sun.target);
      const material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        flatShading: true,
        roughness: 1,
      });
      const rockMaterial = new THREE.MeshStandardMaterial({
        color: '#82735f',
        flatShading: true,
        roughness: 1,
      });
      const rockGeometry = new THREE.DodecahedronGeometry(1, 0);
      const trunkGeometry = new THREE.CylinderGeometry(0.07, 0.1, 0.72, 5);
      const crownGeometry = new THREE.ConeGeometry(0.46, 0.9, 6);
      const trunkMaterial = new THREE.MeshStandardMaterial({
        color: '#5d4933',
        roughness: 1,
      });
      const crownMaterials = ['#344a38', '#425c3d', '#526847'].map(
        (color) =>
          new THREE.MeshStandardMaterial({
            color,
            roughness: 1,
            flatShading: true,
          }),
      );
      const seamPoints: number[] = [];
      let triangles = 0,
        rocks = 0,
        trees = 0;
      const seamX = new Set([centerChunk.x * 128, (centerChunk.x + 1) * 128]);
      const seamZ = new Set([centerChunk.z * 128, (centerChunk.z + 1) * 128]);
      for (let x = centerChunk.x - 1; x <= centerChunk.x + 1; x++)
        for (let z = centerChunk.z - 1; z <= centerChunk.z + 1; z++) {
          const data = meshChunk(world, { x, z });
          const geometry = new THREE.BufferGeometry();
          geometry.setAttribute(
            'position',
            new THREE.BufferAttribute(data.positions, 3),
          );
          geometry.setAttribute(
            'normal',
            new THREE.BufferAttribute(data.normals, 3),
          );
          geometry.setAttribute(
            'color',
            new THREE.BufferAttribute(data.colors, 3),
          );
          const mesh = new THREE.Mesh(geometry, material);
          mesh.name = `chunk-${x}-${z}`;
          mesh.castShadow = true;
          mesh.receiveShadow = true;
          scene.add(mesh);
          triangles += data.positions.length / 9;
          // Show only actual shared mesh edges, following both ground and overhangs.
          for (let i = 0; i < data.positions.length; i += 9)
            for (let v = 0; v < 3; v++) {
              const a = i + v * 3,
                b = i + ((v + 1) % 3) * 3,
                p = data.positions;
              if (
                (p[a] === p[b] && seamX.has(p[a])) ||
                (p[a + 2] === p[b + 2] && seamZ.has(p[a + 2]))
              ) {
                seamPoints.push(
                  p[a],
                  p[a + 1] + 0.08,
                  p[a + 2],
                  p[b],
                  p[b + 1] + 0.08,
                  p[b + 2],
                );
              }
            }
          for (const placement of chunkPlacements(world, { x, z })) {
            if (placement.kind === 'tree') {
              const tree = new THREE.Group();
              tree.name = placement.id;
              const trunk = new THREE.Mesh(trunkGeometry, trunkMaterial);
              trunk.position.y = 0.36;
              trunk.castShadow = true;
              tree.add(trunk);
              for (let layer = 0; layer < 3; layer++) {
                const crown = new THREE.Mesh(
                  crownGeometry,
                  crownMaterials[
                    (layer + Math.abs(x + z)) % crownMaterials.length
                  ],
                );
                crown.position.y = 0.75 + layer * 0.28;
                crown.scale.setScalar(1 - layer * 0.17);
                crown.rotation.y = placement.yaw + layer * 0.7;
                crown.castShadow = true;
                tree.add(crown);
              }
              tree.position.set(...placement.position);
              tree.scale.setScalar(placement.scale);
              scene.add(tree);
              trees++;
            } else {
              const rock = new THREE.Mesh(rockGeometry, rockMaterial);
              rock.name = placement.id;
              rock.position.set(...placement.position);
              rock.scale.set(
                placement.scale * 1.2,
                placement.scale * 0.65,
                placement.scale,
              );
              rock.rotation.set(
                placement.yaw * 0.13,
                placement.yaw,
                placement.yaw * 0.08,
              );
              rock.castShadow = true;
              scene.add(rock);
              rocks++;
            }
          }
        }
      const seams = new THREE.LineSegments(
        new THREE.BufferGeometry().setAttribute(
          'position',
          new THREE.Float32BufferAttribute(seamPoints, 3),
        ),
        new THREE.LineBasicMaterial({ color: '#e47633' }),
      );
      seams.visible = boundaries;
      scene.add(seams);
      const camera = new THREE.PerspectiveCamera(42, 1, 0.5, 2000);
      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.minDistance = 25;
      controls.maxDistance = 650;
      controls.maxPolarAngle = Math.PI * 0.52;
      engine.current = { camera, controls, seams };
      positionCamera();
      const resize = () => {
        const { width, height } = mount.getBoundingClientRect();
        renderer!.setSize(width, height);
        camera.aspect = width / Math.max(height, 1);
        camera.updateProjectionMatrix();
      };
      observer = new ResizeObserver(resize);
      observer.observe(mount);
      resize();
      const draw = () => {
        frame = requestAnimationFrame(draw);
        controls!.update();
        renderer!.render(scene, camera);
      };
      draw();
      setStats({
        triangles,
        rocks,
        trees,
        milliseconds: Math.round(performance.now() - start),
      });
      return () => {
        cancelAnimationFrame(frame);
        observer?.disconnect();
        controls?.dispose();
        disposeGroup(scene);
        seams.geometry.dispose();
        (seams.material as THREE.Material).dispose();
        sun.shadow.map?.dispose();
        renderer?.dispose();
        renderer?.forceContextLoss();
        renderer?.domElement.remove();
        engine.current = null;
      };
    } catch (e) {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      controls?.dispose();
      disposeGroup(scene);
      renderer?.dispose();
      renderer?.forceContextLoss();
      renderer?.domElement.remove();
      engine.current = null;
      setError(e instanceof Error ? e.message : 'World preview failed');
    }
    // Seed/location create a fixed nine-chunk preview; streaming belongs to SF-03.
  }, [center.id, seed, spec]);

  function positionCamera() {
    const e = engine.current;
    if (!e) return;
    const x = center.x,
      y = center.y,
      z = center.z;
    if (view === 'top') {
      e.camera.position.set(x, 540, z + 0.01);
      e.controls.target.set(x, 12, z);
    } else if (view === 'opening') {
      e.camera.position.set(
        x + center.extent[0] * 0.08,
        y,
        z + center.extent[2] * 0.95,
      );
      e.controls.target.set(x, y, z);
    } else if (view === 'detail') {
      e.camera.position.set(
        x + center.extent[0] * 0.82,
        y + center.extent[1] * 0.65,
        z + center.extent[2] * 0.98,
      );
      e.controls.target.set(x, y, z);
    } else {
      e.camera.position.set(x + 310, 225, z + 350);
      e.controls.target.set(x, 20, z);
    }
    e.controls.update();
  }
  useEffect(positionCamera, [view, center.id]);
  useEffect(() => {
    if (engine.current) engine.current.seams.visible = boundaries;
  }, [boundaries]);

  const validSeed = /^\d+$/.test(draftSeed) && Number(draftSeed) <= 4294967295;
  return (
    <main className="world-page">
      <header className="world-header">
        <a href="./">← Preset editor</a>
        <span>STRATA / CONNECTED WORLD</span>
        <span className="world-version">World preview</span>
      </header>
      <section className="world-intro">
        <div>
          <p className="world-eyebrow">ONE LANDSCAPE, CONTINUOUS GROUND</p>
          <h1>A world beyond the edge.</h1>
          <p>
            2,048 × 2,048 metres. Arches, tunnels and outcrops on connected
            terrain.
          </p>
        </div>
        <div className="world-extent">
          <strong>256</strong>
          <span>chunks · 128 m each</span>
        </div>
      </section>
      <section className="world-panel" aria-label="Connected world preview">
        <form
          className="world-toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            if (validSeed) setSeed(Number(draftSeed));
          }}
        >
          <label>
            World seed
            <input
              type="number"
              min="0"
              max="4294967295"
              step="1"
              aria-label="Connected world seed"
              value={draftSeed}
              onChange={(e) => setDraftSeed(e.target.value)}
            />
          </label>
          <button type="submit" disabled={!validSeed}>
            Generate world
          </button>
          <label>
            Location
            <select
              aria-label="World location"
              value={location}
              onChange={(e) => setLocation(Number(e.target.value))}
            >
              {locations.map((l, i) => (
                <option value={i} key={l.name}>
                  {l.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            View
            <select
              aria-label="World camera"
              value={view}
              onChange={(e) => setView(e.target.value)}
            >
              <option value="oblique">Landscape</option>
              <option value="detail">Landmark detail</option>
              <option value="top">From above</option>
              <option value="opening">Ground level</option>
            </select>
          </label>
          <label className="world-checkbox">
            <input
              type="checkbox"
              checked={boundaries}
              onChange={(e) => setBoundaries(e.target.checked)}
            />
            Chunk boundaries
          </label>
        </form>
        <div
          className="world-canvas"
          ref={host}
          aria-label="Connected terrain. Drag to orbit, scroll to zoom."
          data-seed={seed}
          data-location={location}
          data-triangles={error ? 0 : stats.triangles}
          data-features={spec.features.length}
          data-trees={stats.trees}
          data-rocks={stats.rocks}
        >
          {error && <div role="alert">World preview unavailable: {error}</div>}
        </div>
        <div className="world-status" role="status">
          <span>9 connected chunks · 384 × 384 m preview</span>
          <span>
            {stats.triangles.toLocaleString()} faces · {stats.trees} trees ·{' '}
            {stats.rocks} rocks · {stats.milliseconds} ms generation
          </span>
        </div>
      </section>
      <footer className="world-footer">
        <p>
          Viewing X {(centerChunk.x - 1) * 128}…{(centerChunk.x + 2) * 128} m, Z{' '}
          {(centerChunk.z - 1) * 128}…{(centerChunk.z + 2) * 128} m. Drag to
          orbit; right-drag to pan.
        </p>
        <p>
          This preview loads nine fixed chunks. World streaming and free
          navigation are next.
        </p>
      </footer>
    </main>
  );
}
