# SF-13 iteration 1: scan-time rig motion and calibration drift

Accepted iteration scope, 2026-10-19. Branch:
`feature/temporal-capture-calibration-drift`. RED checkpoint: `9145041`.
GREEN implementation: `0e1a20e922c46ef4caeabb6a9ff3ca1fa3ed2097`.
**Full SF-13 remains IN PROGRESS.** Sequence jobs, moving objects, replay recovery
and temporal split isolation are not claimed by this iteration.

## Delivered behavior

Optional canonical `TemporalCapture` drives actual rig/sensor transforms at each
camera/beam sample. Platform velocity and yaw, plus sensor translation/yaw and
their drift rates, are explicit. The LiDAR returns instantaneous sensor-frame
points; observable `timed-sensor.v1` declares timestamp-relative point offsets.
Nominal calibration stays in ObservationBundle. Actual anchor calibration and
the reconstructible motion descriptor stay in worker metadata/TruthBundle.
Python independently checks the worker's actual calibration before publication.
See [physical and time conventions](../TEMPORAL_CAPTURE.md).

The frozen SF-11/SF-Q datasets, weights, preprocessing and accepted ensemble were
not changed. No training or detector-quality improvement is claimed.

## Tests and evidence

Initial RED commands were `node --experimental-strip-types --test
tests/sensors/temporal.test.ts` and, with `PYTHONPATH=backend`,
`backend/.venv/Scripts/python.exe -m pytest backend/tests/test_temporal_capture.py -q`.
Both failed on the intended absent implementation modules: `temporal.ts` and
`app.temporal_capture`. The RED commit retains the tests. GREEN adds the
implementation and resolves two test setup issues: use the contracts validator
without Node's generated `.js` type-export resolution, and use a floating-point
array for the independent NumPy rotation oracle (integer arrays truncate it).

| Guarantee | Verification | Result |
| --- | --- | --- |
| Moving-platform wall ranges follow the analytical traveled distance | `tests/sensors/temporal.test.ts` | PASS |
| Static/zero motion are identical; timestamp offset is applied once | Same tests | PASS |
| Drift transforms match an independent row-major translation/yaw oracle | `backend/tests/test_temporal_capture.py` | PASS |
| Inconsistent/missing actual calibration is rejected; nominal stays unchanged | Same tests and real-worker acceptance | PASS |
| Shared shape/version/duplicate drift and observable sampling conventions | Shared contract fixtures, both runtimes | PASS |
| 25 data/preview artifacts match static repeat and zero motion exactly | Six-capture real GPU worker acceptance | PASS |
| Moving scan is reproducible and changes LiDAR; drift changes RGB | Same acceptance | PASS |
| Per-return offsets equal duration times beam index, relative to sensor timestamp | Same acceptance with nonzero sensor offsets | PASS |
| Model input loads without truth/annotations/worker metadata | Isolated observation-only directory, 11 arrays | PASS |
| All backend behavior, including learning | `PYTHONPATH=backend; python -m pytest backend/tests -q` | 229 passed, no skips |
| Contracts, TS, world/sensor/assets, API tests and production build | `npm run verify` | exit 0; 147 API-env tests passed, 8 ML modules skipped there |
| Sensor regression | `npm run test:sensors` | 35 passed |
| Production Edge GPU UI, capture, cancellation, browser closure, weather/thermal replay | Playwright capture/weather/backend specs | 7 passed |

Targeted coverage: `temporal.ts` 100% lines / 87.5% branches; Python temporal
boundary 93% statements. This is coverage of the new modules, not a whole-project
coverage claim. Production browser checks exercise the candidate rendering;
the later additive sampling metadata is covered by final contract tests and
the final real-worker run on the clean GREEN commit.

Final acceptance used six 640x384 RGB/IR, 32x256 LiDAR captures with a separate
100 ms scan fixture. The first attempted integration fixture still had the
static generator's zero scan duration: motion correctly produced no scan-time
change and the motion-change assertion failed. The corrected nonzero-duration
fixture passed. The failed log is retained, not counted as acceptance.

## GPU analysis

Recorded Windows, Python 3.13.10, PyTorch 2.13.0+cu130, RTX 3090, driver 591.86,
370 W power limit, actual NVIDIA D3D11 renderer. Capture uses `backend/.venv`;
the existing CUDA-capable `python` ran inference/full backend tests. The local
`backend/.venv-learning` currently lacks torch; it was not silently used or changed.
No unrelated process was stopped. NVIDIA readings are device-wide; WDDM reports
unavailable per-process memory for other listed processes.

| Workload | Measured runtime | GPU use / power / temperature |
| --- | --- | --- |
| Six-capture acceptance, including startup/publication | 13.57 s; first frame 5.55 s, warm static 1.30 s | whole command mean 7.85%, 91.42 W; max 144.20 W; max 54 C |
| Unchanged 18-head ensemble, 10 warmups + 200 measured calls | p50 67.46 ms / p95 75.54 ms; 14.36 captures/s; model load 0.395 s separate | steady window mean 25.57%, 77.00 W; peak 124.40 W; 49..53 C; device memory 2016..2020 MiB |

An earlier unchanged-ensemble repeat measured p50/p95 76.22/88.09 ms, steady
GPU 27.13% and 71.85 W. This variation under shared desktop load is retained;
the later lower latency is **not an optimization claim**.

Cold capture spends 2427 ms meshing on CPU. Warm static phases include RGB and
reference work 310 ms, visibility 131 ms, thermal 33 ms, LiDAR BVH 17 ms and CPU
scan 41 ms; readback/encoding/publication and subprocess boundaries remain in
end-to-end wall time. Warm moving/drifting scans measured about 50 ms. A single
frame is not a sustained multi-worker collection benchmark.

In a separate instrumented 10-call inference pass, host cumulative costs per
capture were observation read/hash/schema validation 20.97 ms, preprocessing
4.55 ms and consensus 7.20 ms. Eighteen model forwards are sequential, with
prediction transfer after each. CUDA forward stream spans summed to 46.73 ms
per capture, including launch gaps. These are not active-kernel measurements;
cProfile costs overlap through callers and perturb runtime.

The user's >300 W / about 70 C working reference was not reached. Device memory
use is small, and the measured pipeline contains substantial host work and
sequential launches. A compute-only saturation or thermal-limit diagnosis is not
established. Batching/graph replay, parallel model execution and input validation
cost are candidates for a separate matched optimization iteration, with prediction
parity and end-to-end throughput gates. No performance default changed here.

## Reproduction and provenance

Commands and fresh-output requirements are in [the profile](../TEMPORAL_CAPTURE.md).
Final real-worker and ensemble profiling ran on clean `0e1a20e`; their telemetry
records `source_dirty: false`. Raw GPU CSV, phase records, regression logs,
the failed zero-duration fixture and both ensemble measurements are published
under [sf13-rig](sf13-rig/artifact-manifest.json). The source manifest hashes
exact implementation Git blobs. PowerShell UTF-16 logs are transcribed to UTF-8
for publication; artifact hashes identify those published bytes.

Raw captures, traces, checkpoints and full data stay under ignored artifacts.
Historical static SF-Q quality evidence remains scoped to its original protocol.
