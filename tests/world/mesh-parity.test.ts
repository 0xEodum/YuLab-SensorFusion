import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import {
  aerodromeWorldSpec,
  createWorld,
  defaultWorldSpec,
  harborWorldSpec,
  meshChunk,
} from "../../packages/world/src/index.ts";

const meshHash = (m: ReturnType<typeof meshChunk>) => {
  const h = createHash("sha256");
  for (const a of [m.positions, m.normals, m.colors])
    h.update(new Uint8Array(a.buffer, a.byteOffset, a.byteLength));
  return h.digest("hex");
};

test("column density is bit-equal to point density on every generator profile", () => {
  for (const spec of [
    defaultWorldSpec(48291),
    aerodromeWorldSpec(48291, [], "background"),
    harborWorldSpec(7, [], "background"),
  ]) {
    const world = createWorld(spec);
    for (let i = 0; i < 400; i++) {
      // Deterministic spread over the domain, including feature interiors.
      const x = -1000 + ((i * 7919) % 2000) + 0.37,
        z = -1000 + ((i * 104729) % 2000) - 0.61;
      const column = world.densityColumn(x, z);
      for (let y = -32; y <= 96; y += 6.5)
        assert.ok(Object.is(column(y), world.density(x, y, z)), `${spec.world_id} ${x},${y},${z}`);
    }
  }
});

test("optimized meshing reproduces pre-optimization chunk bytes", () => {
  // Hashes recorded from the original meshChunk/density implementation (93c8d67).
  const cases: [Parameters<typeof createWorld>[0], { x: number; z: number }, 2 | 4, string][] = [
    [defaultWorldSpec(48291), { x: -1, z: -1 }, 2,
      "f61075dd14c61ecbf3468ea8aa3aae729774a7ac1f69255d02f08cb53258deab"],
    [aerodromeWorldSpec(48291, [], "background"), { x: 1, z: 2 }, 2,
      "9a1360b09a79a9ef2cd64820f7dc4559791301812a4418ae18d2fcdfabadc904"],
    [harborWorldSpec(7, [], "background"), { x: 0, z: 0 }, 2,
      "c2379b288e16b4225e1623a92809fb3fe11cf7c5ffb650ab4bc7326ba7ee3bbd"],
    [defaultWorldSpec(0), { x: -6, z: -3 }, 4,
      "15a6ff169520512fe90a1e125961929984bd7dcc39e86e954b7d556edd2592cd"],
  ];
  for (const [spec, coord, pitch, expected] of cases)
    assert.equal(meshHash(meshChunk(createWorld(spec), coord, pitch)), expected,
      `${spec.world_id} ${coord.x},${coord.z}@${pitch}`);
});
