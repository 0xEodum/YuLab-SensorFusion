# SF-03 streaming and navigation evidence

Date: 2026-09-21. Implementation checkpoint: `0c6c456`. Verification is local
only. Source, fixture, build and artifact identities are recorded in
[sf03-verification-manifest.json](sf03-verification-manifest.json). The evidence
commit refers to the tested implementation checkpoint; it does not introduce
an impossible self-referential source hash.

## Delivered behavior

The connected explorer now streams a moving 3 Г— 3 neighborhood in a dedicated
generation worker. Overlapping neighbors reuse a bounded LRU cache; superseding
navigation terminates active generation and discards stale results. Whole-set
leases keep the previous display available until its replacement is complete.
Geometry and instance buffers are disposed when chunks leave the display.
Shared decoration primitives use per-chunk instancing with stable placement-ID
tables. Region shortcuts and seed changes retain the prior world/editor behavior.

Orbit/pan and keyboard/drag free flight work throughout the finite domain. Named
inspection-rig poses persist per world seed, including position, quaternion,
target, navigation mode and detail. Display LOD changes atomically between 4 m
and 2 m neighborhoods. Independent sensor residency uses fixed 2 m geometry and
the union of complete sensor range coverage, independent of display culling or
LOD. Failure/cancellation/capacity never yields a successful partial lease.

[STREAMING.md](../STREAMING.md) defines ownership, bounds, frames, cancellation,
LOD, finite-world behavior and the later capture integration boundary. No field,
placement or legacy-generator semantics changed; no wire-schema bump is needed.

## Acceptance and regression results

| Check | Exit | Result |
| --- | --- | --- |
| `npm run verify` | 0 | Generated contracts, all TypeScript, 62 contract tests, 19 world tests, 72 backend tests and production build passed |
| `npm run verify:world` | 0 | Two full 256-chunk sweeps, 480 seams and 262,144 vertical probes per seed, topology and shuffled replay passed |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_GPU=1 PLAYWRIGHT_TEST_BUILT=1 npm run test:browser` | 0 | All 11 production-browser tests passed, including 104 adjacent crossings and frame-time gates |
| `PLAYWRIGHT_CHANNEL=msedge npx playwright test --grep-invert "104 adjacent"` | 0 | All 10 development-server software-WebGL compatibility tests passed; no hardware performance claim from this run |

World hashes remain `17824b2a08230c8a234463b6678e8069c11393fb2c163518b9e82dfa4957ef35`
(seed 0) and `ca7133fcde66cb79f1eb68ecd7a5ad321bb3b54b09f23c6db09ec88887743c42`
(seed 48291). Complete sweeps took 75.7 and 82.2 seconds. Prior SF-02R reports and
screenshots were preserved; SF-03 rerun artifacts are archived separately.

The new deterministic tests cover pinned LRU eviction over 110 boundary
transitions, late-result cancellation, capacity/byte exhaustion, generation
failure, wrong chunk identity, negative coordinates, range unions, protruding
neighbor decorations, delayed readiness and asynchronous readback pinning.
Consumer failure/cancellation releases all leases. Bookmark fixtures reject
wrong versions/worlds, invalid quaternions, sparse/nonfinite vectors and
out-of-domain positions.

The real occlusion fixture starts at (127.9, 80, 64) m, looks east/down across
x=128, and intersects the actual fixed-2-m triangle mesh in chunk (1,0). That
chunk is absent from the west-facing display fixture. The capture callback waits
for its geometry, and the nearest hit belongs to the neighboring chunk. This
verifies residency gating and triangle occlusion, not an implemented LiDAR/RGB
pipeline. RGB/IR/LiDAR simulation and calibrated rigs remain later stages.

Browser checks exercise real worker failure, domain corners, keyboard flight,
pose save/reload/restore, in-flight cancellation, 4-to-2-to-4 m display switching,
independent sensor preparation, seed teardown and GPU/CPU resource disposal.
The full legacy editor/export, backend, seed-repeat, landmark and mobile suites
remain green. No unexpected page errors occurred.

## Production traversal and performance

Environment: Windows 11 Pro 10.0.26200, Intel Core i5-12400 (6 cores / 12 threads),
34,088,599,552 bytes physical RAM, NVIDIA RTX 3090 / 24,576 MiB, driver 591.86.
Node 25.6.1, npm 11.9.0, Python 3.13.10, uv 0.12.17, Playwright 1.63.0, Edge
153.0.4234.48. The reported GPU renderer is ANGLE NVIDIA RTX 3090 / Direct3D11;
this performance run did not use SwiftShader.

Profile: seed 0, 1280 Г— 720 canvas, DPR 1, antialiasing, 2048ВІ static shadow map,
4 m display cells, nine displayed chunks, boundary overlay enabled. A 105-pose
serpentine route crosses 104 adjacent chunk boundaries through negative and
positive coordinates, then returns to its evicted starting region. Sampling
resets after the first 12 crossings. Each destination waits for actual worker
readiness; this measures streaming navigation with loading intervals, not
zero-latency teleportation or unlimited-speed flight.

| Measurement | Recorded result |
| --- | --- |
| Rendered neighbor pairs checked | 1,260; exact position/normal/color boundary agreement |
| Stale resident sets / duplicate or changed placement IDs | 0 |
| Terrain faces after warmup | 79,670..106,372 per displayed neighborhood |
| Decorations after warmup | 1..223 trees, 102..335 rocks |
| Frame time p50 / p95 / max | 16.7 / 16.9 / 33.3 ms, 2,999 recorded intervals |
| Fresh worker generation p50 / p95 | 126.7 / 181.2 ms per chunk, 237 post-warmup results |
| Neighborhood load p50 / p95 | 376 / 477 ms after warmup, including cache hits |
| Main-thread commit p50 / p95 | 1.0 / 1.7 ms |
| Display cache after warmup | 24 entries; peak retained accounting 27,885,584 bytes (26.6 MiB), below 128 MiB |
| Renderer geometry count | 15..21, bounded through traversal |
| Owned resources created / disposed / live at return | 1,987 / 1,924 / 63 |
| Forced-GC main V8 heap | 9,039,988..9,511,752 bytes; nonmonotonic, within the recorded bound |
| Main ArrayBuffer backing store | 26,502,308..28,523,872 bytes across forced-GC checkpoints |

The architecture target of >=30 fps median and <=50 ms p95 is met for this
hardware/scene profile and remains unchanged. Cache/resource limits are asserted
throughout the route. Actual seed teardown additionally verifies zero cache
bytes, zero live owned resources, equal created/disposed counts and a detached
canvas. Numerical seam checks inspect the rendered buffers; instance IDs inspect
the real renderer's per-instance tables.

Direct inspection of overview, end-of-traversal and fine-detail screenshots
shows continuous ground and formation edges with matching material transitions.
The orange seam overlay follows the shared terrain edges; no mismatched-pitch
cracks are present. The low-poly terrain, vegetation and formations remain
recognizable. This is visual inspection plus numerical seam acceptance, not an
automated image-difference claim.

## Limits

- LOD is whole-neighborhood atomic switching. Mixed-pitch transition meshes are
  not implemented; this policy satisfies display LOD without adding seam gaps.
- Resident boundaries are visible finite cuts. Rapid flight may outrun loading;
  the old neighborhood and loading status remain until the new one is ready.
- Sensor range coverage is conservative and limited to 32 chunks / 128 MiB.
  Larger acquisitions fail explicitly. Imported assets require actual bounds
  in their later stages; current v2 decorations use an 8 m ownership margin.
- Memory figures distinguish retained geometry, main-isolate heap/backing store
  and GPU resource counts. They do not measure total GPU-driver allocation or
  worker/process RSS; a single in-flight mesh and mesher temporaries lie outside
  retained-cache accounting. No total-process memory ceiling is claimed.
- Free flight is inspection navigation without collision physics. Saved poses
  use the Three.js camera frame, not a calibrated RigSpec. Sensor capture,
  observations, datasets and model training remain unavailable.

SF-03 is DONE. SF-04 is the sole READY item.
