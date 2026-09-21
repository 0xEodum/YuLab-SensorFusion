import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { OBJExporter } from 'three/addons/exporters/OBJExporter.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { createTerrain, disposeGroup, setupScene, type TerrainConfig } from './terrain';

export type SceneStats = { triangles: number; vertices: number; resolution: number; time: number };
export type ViewportHandle = { reset: () => void; zoom: (amount: number) => void; top: () => void; exportFile: (type: 'glb' | 'obj' | 'png') => Promise<void> };
type Props = { config: TerrainConfig; wireframe: boolean; grid: boolean; autoRotate: boolean; tool: string; onStats: (stats: SceneStats) => void; onFps: (fps: number) => void };
function saveFile(data: BlobPart, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
const TerrainViewport = forwardRef<ViewportHandle, Props>(function TerrainViewport({ config, wireframe, grid, autoRotate, tool, onStats, onFps }, ref) {
  const mount = useRef<HTMLDivElement>(null);
  const engine = useRef<{ renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls; terrain?: THREE.Group; grid: THREE.GridHelper } | null>(null);
  const [error, setError] = useState(false);
  const fpsCallback = useRef(onFps); fpsCallback.current = onFps;
  const configRef = useRef(config); configRef.current = config;
  useImperativeHandle(ref, () => ({
    reset() { const e = engine.current; if (e) { e.camera.position.set(19, 13, 25); e.controls.target.set(0, 2.5, 0); e.controls.update(); } },
    zoom(amount) { const e = engine.current; if (e) { const v = e.camera.position.clone().sub(e.controls.target); v.multiplyScalar(amount); v.clampLength(16, 85); e.camera.position.copy(e.controls.target).add(v); e.controls.update(); } },
    top() { const e = engine.current; if (e) { e.camera.position.set(0, 40, .1); e.controls.target.set(0, 0, 0); e.controls.update(); } },
    async exportFile(type) {
      const e = engine.current; if (!e?.terrain) throw new Error('The scene is not ready yet.');
      const filename = `strata-${configRef.current.preset}-${configRef.current.seed}`;
      if (type === 'png') {
        e.renderer.render(e.scene, e.camera);
        const blob = await new Promise<Blob | null>(resolve => e.renderer.domElement.toBlob(resolve, 'image/png'));
        if (!blob) throw new Error('Could not capture the image.');
        saveFile(blob, `${filename}.png`, 'image/png');
      } else if (type === 'obj') {
        saveFile(new OBJExporter().parse(e.terrain), `${filename}.obj`, 'text/plain');
      } else {
        const result = await new GLTFExporter().parseAsync(e.terrain, { binary: true });
        saveFile(result as ArrayBuffer, `${filename}.glb`, 'model/gltf-binary');
      }
    },
  }), []);
  useEffect(() => {
    if (!mount.current) return;
    const host = mount.current;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }); } catch { setError(true); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
    host.appendChild(renderer.domElement);
    const scene = setupScene();
    const camera = new THREE.PerspectiveCamera(30, 1, .1, 200);
    camera.position.set(19, 13, 25);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 2.5, 0); controls.enableDamping = true; controls.dampingFactor = .08; controls.minDistance = 16; controls.maxDistance = 85;
    controls.maxPolarAngle = Math.PI * .52; controls.autoRotateSpeed = .55; controls.update();
    const gridHelper = new THREE.GridHelper(48, 32, '#b5b0a5', '#ccc7bc'); gridHelper.position.y = -2.85;
    (gridHelper.material as THREE.Material).transparent = true; (gridHelper.material as THREE.Material).opacity = .38; gridHelper.visible = false; scene.add(gridHelper);
    engine.current = { renderer, scene, camera, controls, grid: gridHelper };
    const resize = () => { const { width, height } = host.getBoundingClientRect(); renderer.setSize(width, height); camera.aspect = width / Math.max(height, 1); camera.fov = Math.min(55, 30 * Math.max(1, 1.55 / camera.aspect)); camera.updateProjectionMatrix(); };
    const observer = new ResizeObserver(resize); observer.observe(host); resize();
    let frame = 0, frames = 0, start = performance.now();
    const tick = () => {
      frame = requestAnimationFrame(tick); controls.update(); renderer.render(scene, camera); frames++;
      const now = performance.now(); if (now - start > 1200) { fpsCallback.current(Math.min(144, Math.round(frames * 1000 / (now - start)))); frames = 0; start = now; }
    }; tick();
    return () => { cancelAnimationFrame(frame); observer.disconnect(); controls.dispose(); disposeGroup(scene); gridHelper.geometry.dispose(); (gridHelper.material as THREE.Material).dispose(); renderer.dispose(); renderer.forceContextLoss(); if (host.contains(renderer.domElement)) host.removeChild(renderer.domElement); engine.current = null; };
  }, []);
  useEffect(() => {
    const e = engine.current; if (!e) return;
    const start = performance.now();
    const { group, triangles, vertices, resolution } = createTerrain(config);
    if (e.terrain) { e.scene.remove(e.terrain); disposeGroup(e.terrain); }
    e.terrain = group; e.scene.add(group);
    group.traverse(obj => { if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) obj.material.wireframe = wireframe; });
    onStats({ triangles, vertices, resolution, time: Math.round(performance.now() - start) });
  }, [config, onStats]);
  useEffect(() => {
    const e = engine.current; if (!e) return;
    e.grid.visible = grid; e.controls.autoRotate = autoRotate;
    e.controls.mouseButtons.LEFT = tool === 'pan' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    e.terrain?.traverse(obj => { if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) obj.material.wireframe = wireframe; });
  }, [wireframe, grid, autoRotate, tool]);
  return <div ref={mount} className={`terrain-canvas ${tool === 'pan' ? 'pan-cursor' : ''}`} aria-label="Interactive 3D terrain. Drag to orbit, scroll to zoom, right-drag to pan.">{error && <div className="webgl-error"><strong>3D rendering is unavailable</strong><p>Enable WebGL or hardware acceleration in your browser to explore your terrain.</p></div>}</div>;
});
export default TerrainViewport;
