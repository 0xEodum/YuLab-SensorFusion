# SF-05 capture worker and reference-pass evidence

Date: 2026-09-22. Tested implementation:
`68258b020e184c0a6746512f16d2ca26732be2c5`. Local acceptance passed. Exact
commands, environment, artifact identities and retained failures are recorded in
the [verification manifest](sf05-verification-manifest.json). The evidence commit
does not claim a self-referential source hash.

## Delivered and inspected

The FastAPI backend owns persistent capture jobs and a capacity-one coordinator.
It invokes a Node-managed headless Chromium worker that reconstructs the same
world, catalog assets, aerodrome and fixed 2 m sensor-residency geometry used by
the browser. Accepted work survives submitting-page closure. Restart interruption,
worker crash, timeout, WebGL context loss and cancellation have explicit terminal
states; `.partial` outputs are validated and atomically published only on success.

The shared `@yulab/sensors` package owns row-major rigid transforms, saved-rig
calibration, optical-frame conversion, projection/ray math, 24-bit ID coding and
raster orientation. Its pure calibration core is separate from the browser-only
WebGL implementation. The initial saved-rig profile is 640 x 384. All three passes
use one frozen scene, camera and tick:

- RGB is sRGB PNG.
- Depth is top-left float32 optical depth in metres, with zero background.
- Instance truth is top-left uint32 with zero background and exact stable IDs.

The UI publishes RGB, depth preview and instance preview only after one succeeded
job and labels them with the same capture ID. Resizing the UI or moving the later
inspection camera does not mutate the accepted rig. Helpers, editor grids,
decorative shadow floors and UI overlays are absent from sensor geometry.

The final captured previews were visually inspected. RGB contains the aerodrome
and aircraft at authored scale; the depth preview has black sky and valid foreground
depth; the instance preview has black background and discrete target regions:

| RGB | Depth preview | Instance preview |
| --- | --- | --- |
| [RGB](sf05/rgb.png) | [Depth](sf05/depth.png) | [Instances](sf05/instance.png) |

Raw NPY acceptance independently checks magic/version, dtype, 640 x 384 shape,
top-left orientation, zero sky, positive surface depth, exact IDs 1..5 and the
requirement that every nonzero ID pixel also has depth.

## TDD and acceptance results

The RED checkpoint `7c30a55` introduced calibration/reference, backend lifecycle
and browser user-journey tests before implementation. It failed for the missing
sensor package, missing backend jobs and absent capture UI. The GREEN checkpoint
`6b14e19` implemented the complete slice. `afc724f` fixed an existing generic
status-selector regression found by the first full browser run; `68258b0` then
isolated the browser renderer from the pure sensor core so meaningful Node coverage
could be reported. The original failed full-suite log is retained.

| Gate | Exit | Result |
| --- | ---: | --- |
| `npm run verify` | 0 | Contract drift/type checks; 64 contract, 19 world, 9 sensor, 4 asset and 81 backend tests; production build |
| `node --test --experimental-test-coverage tests/sensors/*.test.ts` | 0 | 9/9; 100% line, 94.44% branch, 100% function coverage for the pure calibration core |
| Edge/NVIDIA production `npm run test:browser` | 0 | 16/16 journeys in 3.9 min, including capture, cancel, browser-close continuation and 104-boundary regressions |
| `npm run capture:capabilities` | 0 | WebGL2 and float readback on Chromium 153 / RTX 3090 D3D11 |
| Five direct worker captures | 0 | Identical RGB/depth/instance hashes on every run |

Projection fixtures are within 0.5 pixel away from raster boundaries. Tests also
cover rigid/reflected/malformed transforms, exact saved-camera conversion, fixed
dimensions, invalid boundaries, physical occlusion changes from separate sensor
extrinsics, ID round trips, row flipping and helper exclusion. Backend tests cover
queue capacity, success publication, cancellation, crash, timeout, context loss
and restart interruption.

## Throughput and queue decision

The fixed aerodrome request loads 22 sensor chunks and produces five deterministic
artifacts plus metadata. Across five sequential RTX 3090 runs, end-to-end p50/p95
was 14.422/14.457 s and render p50/p95 was 0.531/0.562 s. Median throughput is
4.16 captures/minute. Node RSS p50/p95 was 135.4/135.9 MiB; browser heap was
132.1/133.4 MiB. The renderer does not expose process GPU allocation, so that
measurement is explicitly null. The queue therefore remains capacity one; higher
concurrency is not inferred from VRAM capacity. Samples are in
[capture-benchmark.json](sf05/capture-benchmark.json).

The representative raw hashes are:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| RGB PNG | 19,724 | `404fcd96ac4dc40d5ffb4a2fe306fbf629e02d439bccc7f77eacff3fabfe071f` |
| Depth NPY | 983,120 | `4c6de3009eaa0972b5f2e3562d9f25405ce95ccb7b3444d429863e832e998149` |
| Instance NPY | 983,120 | `ff5af82d8826f2ca6f9963795300979ac2181c78e85b75135957c6c495508bc5` |

## Failures retained and resolved

- The first production suite exposed two pre-existing world tests selecting the
  new always-present status node and one backend test expecting RGB to remain
  unavailable. Capture status is now rendered only for a job/error, and capability
  expectations reflect the implemented service. The unchanged full suite passes.
- The first reference render inherited the scene background into truth targets,
  producing nonzero sky depth/IDs. Reference passes now render a null background;
  raw-array browser assertions prevent recurrence.
- Early artifact IDs containing dots violated the public schema and Node RSS was
  accidentally read as a function. Schema-safe IDs and `process.memoryUsage().rss`
  are covered by final API/worker acceptance.

## Boundaries

SF-05 implements RGB and geometric reference truth, not thermal radiance, LiDAR,
dataset annotations, noise, temporal capture or inference. IR calibration has a
separate baseline for geometry tests but IR remains unavailable until SF-06.
The initial camera is ideal-pinhole and fixed at 640 x 384; instance encoding is
limited to 24-bit nonzero IDs. The Playwright package is pinned, while the local
Edge browser binary is an observed machine dependency. GPU allocation telemetry
and concurrent worker behavior remain uncharacterized, which is why the queue is
not widened. These limits do not remove an SF-05 acceptance requirement.
