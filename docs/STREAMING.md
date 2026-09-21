# Streaming, navigation and residency

SF-03 implements `chunk-residency.v1` over the unchanged `connected-world.v2`
field. The world is finite; rendering an unloaded neighborhood is not evidence
of an empty world. No sensor simulator, capture endpoint or model is advertised.

## Ownership and limits

`WorldRuntime` owns a snapshot, display worker/cache/lease, independent sensor
worker/cache, renderer and shared decoration primitives. Location changes move
the camera without recreating these objects. Seed changes and unmount dispose
the entire runtime. Workers transfer mesh buffers without structured-copying
them; each worker has at most one synchronous generation in flight.

| Resource | Limit / ownership |
| --- | --- |
| Displayed chunks | 3 × 3 around orbit target or flight camera, clipped to finite domain (4..9 chunks) |
| Display retained cache | LRU, at most 24 chunks and 128 MiB of mesh buffers plus 256-byte placement accounting per record |
| Sensor retained cache | Separate LRU, at most 32 chunks and 128 MiB with the same accounting |
| Generation | One in-flight result per worker, outside retained-cache accounting until admission |
| GPU geometry | Only the committed display neighborhood; terrain/edge buffers and instance buffers are disposed on replacement |
| Shared GPU resources | Three decoration geometries, seven materials, light shadow map; disposed with runtime |
| Bookmarks | Last 12 named poses per seed in browser localStorage; same name replaces a pose |
| Telemetry | Bounded 4,096 frame intervals, 512 generation/commit samples |

These are resident geometry/cache limits, not a cap on total browser/GPU process
memory. Meshing has transient lattice, edge-map and output-array allocations;
GPU uploads and the driver have their own memory. Local evidence separately
records exact mesh-buffer accounting, renderer geometry/texture counts, JS heap
and frame/generation times. Placement accounting is conservative metadata
accounting, not an exact measurement of JS object overhead.

An acquisition pins existing hits first, loads missing chunks, and returns a
complete lease. The old display stays pinned and visible until the next whole
neighborhood is ready. Cache capacity/byte exhaustion, worker errors and timeout
(30 seconds per chunk) fail explicitly; there is no lower-quality fallback.
Superseding navigation aborts and terminates active synchronous generation. A
replacement worker initializes the same immutable snapshot. Late responses are
rejected before cache admission or rendering. Pending acquisitions serialize;
concurrent acquisition on the same cache is rejected explicitly. Display and
sensor caches can work independently.

## Display LOD and navigation

Landscape uses 4 m cells; Fine uses 2 m cells. A detail change generates the
complete new neighborhood and commits it atomically. There are no mixed-pitch
neighbors, skirts or transition geometry. This conservative LOD policy preserves
the existing numerical seam contract and true volumetric openings; it costs
more near-view generation than an adaptive transition-mesh scheme. Mixed-pitch
LOD is not required for the SF-03 acceptance targets and is not implemented.

Orbit/pan streams around its focus. Free flight streams around the camera:
click canvas, W/A/S/D move along view/right axes, Q/E move vertically, Shift
accelerates, and drag turns the view. Normal/fast speeds are 45/150 m/s. Input
stays in the focused canvas and clears on blur. X/Z are clamped inside the world;
altitude is -24..800 m. Flight is inspection navigation without collision physics;
it can enter solid terrain. The loading label remains visible until the requested
neighborhood is committed; rapid travel can outrun generation.

`rig-bookmark.v1` stores a name, exact WorldSpec, world position (metres),
normalized quaternion [x,y,z,w], orbit target, navigation mode and detail pitch.
It uses Three.js +Y-up / camera -Z-forward. Validation rejects nonfinite vectors,
unsupported versions, incompatible worlds and out-of-domain horizontal poses.
Restoring an inspection pose does not create calibrated sensor intrinsics or
extrinsics. Conversion to RigSpec belongs to SF-05. Corrupt/unavailable browser
storage reports a visible message. Bookmarks survive reloads but are local to
the browser; no backend durability is claimed.

## Sensor readiness contract

`SensorResidency.capture(ranges, signal, consume)` acquires a **fixed 2 m** lease
before invoking `consume`. The lease stays pinned through its returned promise,
including asynchronous readback; finally releases it after success, failure or
cancellation. Callers must freeze the rig/ranges for the duration. Cancellation
after consumption begins rejects its result but retains geometry until the
consumer settles. The consumer must never publish partial output.

Coverage is the union of all sensor range spheres conservatively projected into
X/Z. No display frustum, facing direction, display LOD or renderer culling enters
this decision. Chunk rectangles expand by 8 m to cover v2 tree/rock horizontal
reach, including rotated rocks, so a neighboring placement may occlude a ray
even when its owning terrain chunk is just outside range. Terrain triangles stay
inside their owning horizontal chunk. Range queries clip to the finite world;
outside the defined world there is no modeled geometry. Sensor origins outside
the horizontal domain are rejected. Oversized range unions fail by named capacity
error instead of dropping far or hidden occluders. Imported assets will require
their actual bounds/residency policy in SF-04/05; the generator currently rejects
them. This gate does not implement RGB/IR/LiDAR capture.

## Local acceptance

```powershell
npm run verify
npm run verify:world
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_GPU='1'
$env:PLAYWRIGHT_TEST_BUILT='1'
npm run test:browser
```

Omit `PLAYWRIGHT_GPU` for the existing software-WebGL compatibility profile;
use the actual GPU renderer reported in the traversal artifact for performance
claims. The 104-adjacent-boundary browser traversal inspects real rendered mesh
boundary positions/normals/colors, per-instance ID tables, cache/GPU disposal
counts, exact resident keys, forced-GC heap samples and frame/generation latency.
The test uses production navigation and workers through an opt-in `?qa=1` handle.
No browser QA code is required for ordinary users. CPU fixtures additionally
test fail-closed readiness, late cancellation, capacity, async readback pinning,
negative coordinates, range unions, bookmarks and actual triangle occlusion just
across a chunk boundary behind a west-facing display.
