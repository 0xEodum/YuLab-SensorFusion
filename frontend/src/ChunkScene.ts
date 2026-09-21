import * as THREE from "three";
import type { ChunkData } from "@yulab/world";

/** Shared decoration primitives, per-chunk instancing and explicit GPU ownership. */
export class ChunkScene {
  readonly root = new THREE.Group();
  readonly stats = { created: 0, disposed: 0, live: 0 };
  private chunks = new Map<
    string,
    { group: THREE.Group; dispose: () => void }
  >();
  private terrain = new THREE.MeshStandardMaterial({
    vertexColors: true,
    flatShading: true,
    roughness: 1,
  });
  private line = new THREE.LineBasicMaterial({ color: "#e47633" });
  private rock = new THREE.DodecahedronGeometry(1, 0);
  private trunk = new THREE.CylinderGeometry(0.07, 0.1, 0.72, 5);
  private crown = new THREE.ConeGeometry(0.46, 0.9, 6);
  private rockMat = new THREE.MeshStandardMaterial({
    color: "#82735f",
    flatShading: true,
    roughness: 1,
  });
  private trunkMat = new THREE.MeshStandardMaterial({
    color: "#5d4933",
    roughness: 1,
  });
  private crowns = ["#344a38", "#425c3d", "#526847"].map(
    (color) =>
      new THREE.MeshStandardMaterial({
        color,
        flatShading: true,
        roughness: 1,
      }),
  );
  private boundaries = false;
  setBoundaries(value: boolean) {
    this.boundaries = value;
    this.root.traverse((o) => {
      if (o instanceof THREE.LineSegments) o.visible = value;
    });
  }
  commit(data: ReadonlyMap<string, ChunkData>) {
    // Construction completes before replacing the displayed set.
    const additions = new Map<
      string,
      { group: THREE.Group; dispose: () => void }
    >();
    try {
      for (const [key, d] of data)
        if (!this.chunks.has(key)) additions.set(key, this.build(d));
    } catch (error) {
      for (const c of additions.values()) c.dispose();
      throw error;
    }
    for (const [key, c] of this.chunks)
      if (!data.has(key)) {
        this.root.remove(c.group);
        c.dispose();
        this.chunks.delete(key);
      }
    for (const [key, c] of additions) {
      this.chunks.set(key, c);
      this.root.add(c.group);
    }
  }
  private build(data: ChunkData) {
    const group = new THREE.Group(),
      owned: THREE.BufferGeometry[] = [],
      instances: THREE.InstancedMesh[] = [];
    const geometry = new THREE.BufferGeometry();
    owned.push(geometry);
    geometry.setAttribute(
      "position",
      new THREE.BufferAttribute(data.mesh.positions, 3),
    );
    geometry.setAttribute(
      "normal",
      new THREE.BufferAttribute(data.mesh.normals, 3),
    );
    geometry.setAttribute(
      "color",
      new THREE.BufferAttribute(data.mesh.colors, 3),
    );
    const mesh = new THREE.Mesh(geometry, this.terrain);
    mesh.name = `terrain:${data.mesh.coord.x},${data.mesh.coord.z}`;
    mesh.castShadow = mesh.receiveShadow = true;
    group.add(mesh);
    const points: number[] = [],
      p = data.mesh.positions,
      { x, z } = data.mesh.coord;
    for (let i = 0; i < p.length; i += 9)
      for (let v = 0; v < 3; v++) {
        const a = i + v * 3,
          b = i + ((v + 1) % 3) * 3;
        if (
          (p[a] === p[b] && (p[a] === x * 128 || p[a] === (x + 1) * 128)) ||
          (p[a + 2] === p[b + 2] &&
            (p[a + 2] === z * 128 || p[a + 2] === (z + 1) * 128))
        )
          points.push(
            p[a],
            p[a + 1] + 0.08,
            p[a + 2],
            p[b],
            p[b + 1] + 0.08,
            p[b + 2],
          );
      }
    const edges = new THREE.BufferGeometry().setAttribute(
      "position",
      new THREE.Float32BufferAttribute(points, 3),
    );
    owned.push(edges);
    const lines = new THREE.LineSegments(edges, this.line);
    lines.visible = this.boundaries;
    group.add(lines);
    const rocks = data.placements.filter((p) => p.kind === "rock"),
      trees = data.placements.filter((p) => p.kind === "tree");
    const instanced = (
      shape: THREE.BufferGeometry,
      material: THREE.Material,
      ids: string[],
      matrix: (i: number) => THREE.Matrix4,
    ) => {
      if (!ids.length) return;
      const m = new THREE.InstancedMesh(shape, material, ids.length);
      // instanceId from ray/raster consumers indexes this immutable stable-ID table.
      m.userData.placementIds = ids;
      ids.forEach((_, i) => m.setMatrixAt(i, matrix(i)));
      m.castShadow = true;
      m.computeBoundingSphere();
      group.add(m);
      instances.push(m);
    };
    const object = new THREE.Object3D(),
      local = new THREE.Object3D();
    instanced(
      this.rock,
      this.rockMat,
      rocks.map((p) => p.id),
      (i) => {
        const p = rocks[i];
        object.position.set(...p.position);
        object.rotation.set(p.yaw * 0.13, p.yaw, p.yaw * 0.08);
        object.scale.set(p.scale * 1.2, p.scale * 0.65, p.scale);
        object.updateMatrix();
        return object.matrix;
      },
    );
    for (let part = -1; part < 3; part++) {
      instanced(
        part === -1 ? this.trunk : this.crown,
        part === -1 ? this.trunkMat : this.crowns[(part + Math.abs(x + z)) % 3],
        trees.map((p) => p.id),
        (i) => {
          const p = trees[i];
          object.position.set(...p.position);
          object.rotation.set(0, 0, 0);
          object.scale.setScalar(p.scale);
          object.updateMatrix();
          local.position.set(0, part === -1 ? 0.36 : 0.75 + part * 0.28, 0);
          local.rotation.set(0, part === -1 ? 0 : p.yaw + part * 0.7, 0);
          local.scale.setScalar(part === -1 ? 1 : 1 - part * 0.17);
          local.updateMatrix();
          return object.matrix.clone().multiply(local.matrix);
        },
      );
    }
    this.stats.created += owned.length + instances.length;
    this.stats.live += owned.length + instances.length;
    return {
      group,
      dispose: () => {
        owned.forEach((g) => g.dispose());
        instances.forEach((m) => m.dispose());
        group.clear();
        this.stats.disposed += owned.length + instances.length;
        this.stats.live -= owned.length + instances.length;
      },
    };
  }
  dispose() {
    for (const c of this.chunks.values()) c.dispose();
    this.chunks.clear();
    this.root.clear();
    [
      this.rock,
      this.trunk,
      this.crown,
      this.terrain,
      this.line,
      this.rockMat,
      this.trunkMat,
      ...this.crowns,
    ].forEach((r) => r.dispose());
  }
}
