# SF-05 through SF-07 synchronized capture

SF-05 adds a backend-owned, single-host capture queue and a Node-managed
headless Chromium worker. The browser preview and worker both use
`@yulab/sensors` for rigid calibration, optical/Three.js frame conversion,
projection and fixed capture dimensions. SF-05 implements RGB plus geometric
depth and instance-ID references. SF-06 adds surface heat, calibrated raw LWIR,
validity/saturation masks, thermal-state replay and a display-only IR preview.
SF-07 adds nearest-surface LiDAR, sparse raw returns and range/point previews.
SF-10 adds geometry-tested RGB/IR visibility labels, posed 3D boxes, LiDAR
instance counts and atomic local dataset publication; see
[DATASET_JOBS.md](DATASET_JOBS.md). Model inference remains planned.

## Frozen capture contract

`CaptureRequest` contains immutable `WorldSpec`, `RigSpec`, `EnvironmentSpec`
and `CapturePlan` values. The backend verifies canonical SHA-256 identities for
the three snapshots and requires one simulation tick. Capture dimensions and
pose come only from the saved rig. Browser resize, later inspection-camera
motion and UI overlays cannot change an accepted job.

World/rig transforms are row-major `T_A_from_B`. A saved Three.js camera uses
the rig's +X right, +Y up, -Z forward frame. Each optical camera uses +X right,
+Y down, +Z forward, with the proper rotation `diag(1,-1,-1)` represented in
`T_rig_from_sensor`. The IR camera has a separate 0.35 m baseline; RGB reference
passes and IR therefore use distinct, calibrated viewpoints.

The worker loads every conservative 2 m sensor-residency chunk within the union
of the RGB and LiDAR maximum ranges before capture. It reconstructs the same world generator,
catalog GLBs and aerodrome structures used by the interactive app. Editor grids,
helpers, decorative shadow floors and UI overlays are not sensor surfaces.

Thermal semantics and declared approximations are specified in
[THERMAL_IR.md](THERMAL_IR.md).
LiDAR beam, response and export semantics are in [LIDAR.md](LIDAR.md).
SF-08 condition presets, spectral attenuation, seeded particles and explicit
time-jump behavior are in [WEATHER.md](WEATHER.md).

## Passes and artifacts

All passes use the same frozen scene and tick. Each optical pass uses its own
saved sensor extrinsic:

- `rgb_png`: 640 x 384 sRGB PNG in the initial saved-rig profile.
- `depth_npy`: top-left H x W little-endian float32 optical depth in metres;
  zero means no opaque surface in range.
- `instance_npy`: top-left H x W little-endian uint32 instance IDs. Zero is
  background. IDs 1..16,777,215 are deterministically assigned by sorted stable
  instance ID and encoded exactly through an unlit, nearest, non-antialiased
  24-bit raster pass.
- `depth_preview_png` and `instance_preview_png`: display-only previews. The ID
  preview deliberately remaps exact low integer IDs to visible colors; it is not
  a training or truth artifact.
- `ir_radiance_npy`: top-left H x W little-endian float32 band-integrated
  radiance in W/(m2 sr), independent of palette and RGB material color.
- `ir_validity_npy` / `ir_saturation_npy`: top-left H x W NPY boolean masks.
- `ir_preview_png`: display-only `iron-v1` fixed-scale color mapping.
- `thermal_state_json`: versioned, hash-addressed surface temperatures used for
  reproducible continued-history capture.
- `lidar_xyz_npy`, `lidar_intensity_npy`, `lidar_beam_id_npy`,
  `lidar_time_offset_npy`, `lidar_validity_npy`: sparse detected returns.
- `lidar_class_ref_npy`: per-return simulator class truth aligned to XYZ;
  labels are excluded from the measured LiDAR observation.
- `lidar_beam_status_npy`: full beam table including no-return/dropout status.
  `lidar_ideal_range_npy`, `lidar_ideal_instance_npy` and
  `lidar_ideal_class_npy` are separate pre-response truth.
- `lidar_cloud_preview_png`: class-colored camera-perspective view.
  `lidar_topdown_preview_png` is the secondary overhead view;
  `lidar_range_preview_png` is the angular range image. All are display only.
- `metadata_json`: renderer/device handshake, timings, CPU/browser memory,
  resident chunks, stable ID map, IR/LiDAR calibration and output hashes.

The worker requires WebGL2 plus `EXT_color_buffer_float`. Capability failure or
context loss is explicit; it is never replaced by RGB recoloring, amodal boxes
or a software-defined fake depth surface.

## Jobs and failure policy

`POST /api/v1/captures` returns a durable `CaptureJob`. Clients poll
`GET /api/v1/jobs/{job_id}`, may cancel with
`POST /api/v1/jobs/{job_id}/cancel`, and read only published artifacts through
the artifact endpoint. Accepted work is owned by the backend and therefore
continues if the submitting browser closes.

The initial measured queue capacity is one worker. Additional jobs remain
`queued`; this avoids concurrent browser/mesh generation before GPU-memory
accounting is available. A worker has a 120 s limit. Crash, timeout, context
loss, restart interruption and cancellation become explicit terminal states.
Artifacts are written under a job-specific `.partial` directory, validated,
then atomically renamed. Failed/cancelled partial files are not addressable and
cannot appear as a succeeded job.

The capability and throughput commands are:

```powershell
$env:PLAYWRIGHT_CHANNEL='msedge'
npm run capture:capabilities
npm run test:browser -- tests/browser/capture.spec.ts
```

The local Edge channel is Chromium-based and its exact browser/WebGL strings are
recorded in evidence. The Playwright package is locked; the machine browser
binary itself is an observed dependency when the bundled Chromium executable is
not installed.

## Dataset throughput

`tools/dataset-job.py` keeps one Node process, asset server, and browser page for
the dataset job. It retains deterministic CPU terrain/placement data for the
current complete WorldSpec snapshot in an LRU cache (64 chunks, 128 MiB). A
changed snapshot clears the cache; new viewpoints generate only missing chunks.
The retention budget never excludes geometry required by a capture. Oversized
chunks are generated normally and are not retained.

Each request builds and disposes its own scene, renderer, asset instances and
LiDAR BVHs. RGB, thermal state/IR, weather/noise, LiDAR, visibility and packaging
all run again with the submitted seeds and calibration. Continued thermal history
still resolves its explicit hash-verified prior artifact. No observations or
labels are cached. Sequential request order, cancellation, the per-request 120 s
timeout and validation before atomic publication remain in effect.

Use the existing collection command; persistent execution is the default:

```powershell
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_GPU='1'
backend\.venv\Scripts\python.exe tools\dataset-job.py --requests REQUESTS.json --output artifacts\DATASET
```

`--single-use` launches a fresh browser for every request as a reference mode.
For a fresh benchmark, use a separate `YULAB_CAPTURE_ROOT` for each run and a new
dataset output directory; `reused_captures` must be zero. Resume retains the
existing validation rules but does not claim fresh-capture throughput.

`tools/compare-capture-datasets.py BEFORE AFTER` validates both manifests and
requires identical file inventories and byte-identical data files, including
previews, raw arrays, masks, calibration, observations, labels and truth.
Only runtime telemetry in `metadata_json` and manifest provenance may differ.
Per-stage timings and cache/memory counters are retained in capture metadata.
The interactive API continues to use isolated single-capture processes.
