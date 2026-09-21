import { useEffect, useRef, useState } from 'react';
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

const locations = [
  { name: 'Central arch', x: 0, z: 0 },
  { name: 'Northern ridge', x: -2, z: -2 },
  { name: 'Island outcrop', x: 2, z: -2 },
  { name: 'Coastal bluff', x: 2, z: 2 },
];

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
    placements: 0,
    milliseconds: 0,
  });
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
      const world = createWorld(defaultWorldSpec(seed));
      const center = locations[location];
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
      sun.position.set(center.x * 128 - 110, 200, center.z * 128 + 130);
      sun.target.position.set(center.x * 128, 10, center.z * 128);
      sun.castShadow = true;
      Object.assign(sun.shadow.camera, {
        left: -200,
        right: 200,
        top: 200,
        bottom: -200,
        near: 1,
        far: 500,
      });
      sun.shadow.mapSize.set(2048, 2048);
      sun.shadow.normalBias = 0.2;
      scene.add(sun, sun.target);
      const material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 1,
      });
      const rockMaterial = new THREE.MeshStandardMaterial({
        color: '#82735f',
        flatShading: true,
        roughness: 1,
      });
      const rockGeometry = new THREE.DodecahedronGeometry(1, 0);
      const seamPoints: number[] = [];
      let triangles = 0,
        placements = 0;
      for (let x = center.x - 1; x <= center.x; x++)
        for (let z = center.z - 1; z <= center.z; z++) {
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
                (p[a] === center.x * 128 && p[b] === center.x * 128) ||
                (p[a + 2] === center.z * 128 && p[b + 2] === center.z * 128)
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
            const rock = new THREE.Mesh(rockGeometry, rockMaterial);
            rock.name = placement.id;
            rock.position.set(...placement.position);
            rock.scale.setScalar(placement.scale);
            rock.rotation.y = placement.yaw;
            rock.castShadow = true;
            scene.add(rock);
            placements++;
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
        placements,
        milliseconds: Math.round(performance.now() - start),
      });
      return () => {
        cancelAnimationFrame(frame);
        observer?.disconnect();
        controls?.dispose();
        disposeGroup(scene);
        seams.geometry.dispose();
        (seams.material as THREE.Material).dispose();
        rockGeometry.dispose();
        rockMaterial.dispose();
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
    // Seed/location create a fixed four-chunk preview; streaming belongs to SF-03.
  }, [seed, location]);

  function positionCamera() {
    const e = engine.current;
    if (!e) return;
    const center = locations[location],
      x = center.x * 128,
      z = center.z * 128;
    if (view === 'top') {
      e.camera.position.set(x, 360, z + 0.01);
      e.controls.target.set(x, 0, z);
    } else if (view === 'opening') {
      e.camera.position.set(x + 5, 33, z + 115);
      e.controls.target.set(x, 35, z);
    } else {
      e.camera.position.set(x + 215, 180, z + 265);
      e.controls.target.set(x, 14, z);
    }
    e.controls.update();
  }
  useEffect(positionCamera, [view]);
  useEffect(() => {
    if (engine.current) engine.current.seams.visible = boundaries;
  }, [boundaries]);

  const validSeed = /^\d+$/.test(draftSeed) && Number(draftSeed) <= 4294967295;
  const center = locations[location];
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
        >
          {error && <div role="alert">World preview unavailable: {error}</div>}
        </div>
        <div className="world-status" role="status">
          <span>4 connected chunks · 256 × 256 m preview</span>
          <span>
            {stats.triangles.toLocaleString()} faces · {stats.placements} rocks
            · {stats.milliseconds} ms generation
          </span>
        </div>
      </section>
      <footer className="world-footer">
        <p>
          Viewing X {(center.x - 1) * 128}…{(center.x + 1) * 128} m, Z{' '}
          {(center.z - 1) * 128}…{(center.z + 1) * 128} m. Drag to orbit;
          right-drag to pan.
        </p>
        <p>
          This preview loads four fixed chunks. World streaming and free
          navigation are next.
        </p>
      </footer>
    </main>
  );
}
