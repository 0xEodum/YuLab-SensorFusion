import { createWorld, meshChunk, chunkPlacements } from "@yulab/world";
import type { WorldSpec } from "@yulab/contracts";
import type { ChunkCoord } from "@yulab/world";

let world: ReturnType<typeof createWorld>;
self.onmessage = (
  event: MessageEvent<{
    id: number;
    spec?: WorldSpec;
    coord: ChunkCoord;
    pitch: 2 | 4;
  }>,
) => {
  const { id, spec, coord, pitch } = event.data;
  try {
    if (spec) world = createWorld(spec);
    if (!world) throw new Error("Worker world not initialized");
    const start = performance.now();
    const mesh = meshChunk(world, coord, pitch);
    const placements = chunkPlacements(world, coord);
    self.postMessage(
      {
        id,
        data: { mesh, placements, generationMs: performance.now() - start },
      },
      {
        transfer: [
          mesh.positions.buffer,
          mesh.normals.buffer,
          mesh.colors.buffer,
        ],
      },
    );
  } catch (error) {
    self.postMessage({
      id,
      error: error instanceof Error ? error.message : String(error),
    });
  }
};
