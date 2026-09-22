# SF-05 RGB and reference capture

SF-05 adds a backend-owned, single-host capture queue and a Node-managed
headless Chromium worker. The browser preview and worker both use
`@yulab/sensors` for rigid calibration, optical/Three.js frame conversion,
projection and fixed capture dimensions. This stage implements RGB plus
geometric depth and instance-ID references; it does not implement thermal IR,
LiDAR, dataset annotations or inference.

## Frozen capture contract

`CaptureRequest` contains immutable `WorldSpec`, `RigSpec`, `EnvironmentSpec`
and `CapturePlan` values. The backend verifies canonical SHA-256 identities for
the three snapshots and requires one simulation tick. Capture dimensions and
pose come only from the saved rig. Browser resize, later inspection-camera
motion and UI overlays cannot change an accepted job.

World/rig transforms are row-major `T_A_from_B`. A saved Three.js camera uses
the rig's +X right, +Y up, -Z forward frame. Each optical camera uses +X right,
+Y down, +Z forward, with the proper rotation `diag(1,-1,-1)` represented in
`T_rig_from_sensor`. The initial IR camera has a separate 0.35 m baseline for
calibration/parallax fixtures, but no IR radiance is captured in SF-05.

The worker loads every conservative 2 m sensor-residency chunk within the RGB
maximum range before rendering. It reconstructs the same world generator,
catalog GLBs and aerodrome structures used by the interactive app. Editor grids,
helpers, decorative shadow floors and UI overlays are not sensor surfaces.

## Passes and artifacts

All passes use the same frozen scene, camera and tick:

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
- `metadata_json`: renderer/device handshake, timings, CPU/browser memory,
  resident chunks, stable ID map and hashes for the other outputs.

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
