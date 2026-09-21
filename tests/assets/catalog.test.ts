import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { validatePayload } from "@yulab/contracts/validate";

const root = new URL("../../frontend/public/catalog/", import.meta.url);
const sha = (b: Buffer) => createHash("sha256").update(b).digest("hex");
test("self-contained catalog preserves provenance, physical scale and semantic mesh references", () => {
  const catalog = JSON.parse(
    readFileSync(new URL("catalog.json", root), "utf8"),
  );
  assert.deepEqual(
    catalog.assets.map((a: any) => a.asset_id),
    ["f16", "rq4", "ground-vehicle"],
  );
  for (const record of catalog.assets) {
    validatePayload("AssetRecord", record);
    const bytes = readFileSync(new URL(`${record.asset_id}.glb`, root));
    assert.equal(sha(bytes), record.content_sha256);
    assert.equal(bytes.length, record.mesh.byte_length);
    assert.equal(bytes.readUInt32LE(0), 0x46546c67);
    const gltf = JSON.parse(
      bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString(),
    );
    const binaryOffset = 20 + bytes.readUInt32LE(12) + 8;
    const attribute = (index: number) => {
      const a = gltf.accessors[index],
        view = gltf.bufferViews[a.bufferView];
      assert.equal(a.componentType, 5126);
      assert.equal(a.type, "VEC3");
      return Array.from({ length: a.count * 3 }, (_, i) =>
        bytes.readFloatLE(
          binaryOffset + (view.byteOffset ?? 0) + (a.byteOffset ?? 0) + i * 4,
        ),
      );
    };
    let triangleCount = 0;
    for (const mesh of gltf.meshes)
      for (const primitive of mesh.primitives) {
        const p = attribute(primitive.attributes.POSITION),
          n = attribute(primitive.attributes.NORMAL);
        assert.ok(p.every(Number.isFinite));
        assert.ok(n.every(Number.isFinite));
        for (let i = 0; i < n.length; i += 3)
          assert.ok(
            Math.abs(Math.hypot(n[i], n[i + 1], n[i + 2]) - 1) < 1e-4,
            `${record.asset_id}: normal length`,
          );
        for (let i = 0; i < p.length; i += 9) {
          const ax = p[i + 3] - p[i],
            ay = p[i + 4] - p[i + 1],
            az = p[i + 5] - p[i + 2];
          const bx = p[i + 6] - p[i],
            by = p[i + 7] - p[i + 1],
            bz = p[i + 8] - p[i + 2];
          const cx = ay * bz - az * by,
            cy = az * bx - ax * bz,
            cz = ax * by - ay * bx;
          const dot =
            cx * (n[i] + n[i + 3] + n[i + 6]) +
            cy * (n[i + 1] + n[i + 4] + n[i + 7]) +
            cz * (n[i + 2] + n[i + 5] + n[i + 8]);
          assert.ok(
            dot >= -1e-6,
            `${record.asset_id}: reflected winding disagrees with normal`,
          );
          triangleCount++;
        }
      }
    assert.equal(gltf.animations, undefined);
    assert.equal(gltf.cameras, undefined);
    assert.ok(gltf.buffers.every((b: any) => !b.uri));
    assert.ok(
      (gltf.images ?? []).every(
        (i: any) => !i.uri && i.bufferView !== undefined,
      ),
    );
    const names = new Set(gltf.nodes.map((n: any) => n.name));
    for (const part of record.parts)
      assert.ok(names.has(part.mesh_node), part.mesh_node);
    assert.ok(record.parts.some((p: any) => p.semantic === "engine-surface"));
    assert.ok(
      record.parts.some(
        (p: any) =>
          p.semantic ===
          (record.asset_id === "ground-vehicle"
            ? "radiator-surface"
            : "exhaust-surface"),
      ),
    );
    const metaBytes = readFileSync(
      new URL(`${record.asset_id}.metadata.json`, root),
    );
    assert.equal(sha(metaBytes), record.metadata.sha256);
    const meta = JSON.parse(metaBytes.toString());
    assert.equal(triangleCount, meta.validation.triangles);
    assert.ok(meta.source_files.length > 0);
    assert.ok(meta.contacts_m.length >= 3);
    assert.ok(meta.contacts_m.every((p: number[]) => Math.abs(p[1]) < 0.015));
    assert.equal(meta.axes, "+X left, +Y up, +Z forward");
    assert.ok(meta.validation.max_normal_error < 0.0001);
    assert.ok(meta.validation.triangles > 1000);
    assert.ok(meta.bounds_min_m[1] > -0.0001);
    assert.equal(record.scale_m_per_source_unit, 1);
  }
  const [f16, rq4, vehicle] = catalog.assets;
  assert.ok(f16.bounds.extent_m[2] > 16 && f16.bounds.extent_m[2] < 17);
  assert.ok(Math.abs(rq4.bounds.extent_m[0] - 39.92) < 0.1);
  assert.ok(vehicle.bounds.extent_m[2] > 10 && vehicle.bounds.extent_m[2] < 12);
});
