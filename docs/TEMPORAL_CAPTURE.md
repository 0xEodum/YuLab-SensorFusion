# Scan-time platform motion and calibration drift

SF-13 iteration 1, 2026-10-19. The optional `CaptureRequest.temporal` payload is
canonical `TemporalCapture`, profile `rig-motion-drift.v1`. It works through the
existing capture worker/API and dataset packager. Requests without this field
keep the existing static behavior. The accepted static ensemble is unchanged
and has not been trained for motion or drift.

## Motion and transform semantics

`request.rig` is the nominal calibration and rig pose at capture anchor time `t`.
At sample offset `d`, platform position is `p(t+d) = p(t) + velocity * d` in world
axes. Left-multiply its orientation by world +Y yaw `yaw_rate_rad_per_s * d`,
rotating around the platform origin.

Each sensor has zero or one drift record. Set `a = t+d-reference_time_s`.
In rig coordinates add `translation_rig_m + translation_rate_rig_m_per_s * a`
to its nominal origin. Left-multiply orientation by rig +Y yaw
`yaw_rad + yaw_rate_rad_per_s * a`. This rotates about that sensor origin,
without rotating its translation. Compose actual rig and sensor transforms in
the existing row-major `T_A_from_B` convention.

The sampler snapshots inputs and rejects non-finite/negative absolute sample
times, duplicate drift modalities and non-rigid calibration. Python independently
recomputes transforms at packaging, rejecting missing or inconsistent provenance.

RGB/IR are global-shutter samples at each sensor timestamp offset. LiDAR evaluates
actual sensor pose for every row-major beam, including timestamp offset exactly
once and spanning its scan duration. Returned XYZ uses the instantaneous sensor
frame. First-opaque-hit, weather and dropout semantics remain unchanged. The
camera preview transforms returns through their sample poses; sensor geometry
residency conservatively bounds the entire platform/sensor sweep.

`ObservationBundle.lidar.data.sampling_profile = "timed-sensor.v1"` declares
instantaneous sensor-frame points and sensor-timestamp-relative offsets, without
exposing actual motion or drift. The optional field defaults to the legacy
`static-capture.v1` convention when absent.
For temporal captures the packaged LiDAR offset array is relative to the
observed LiDAR timestamp: absolute return time equals
`observation.lidar.timestamp_s + time_offset[i]`. Internal `beamFor` offsets
remain capture-relative. Existing static captures retain their historical
capture-relative raw bytes (normally synchronized with offset zero).

## Observation and truth boundary

`ObservationBundle.rig` retains the submitted nominal rig. Actual extrinsics,
drift, velocity and motion truth never enter observations or model features.
Worker results/metadata contain `actual_rig` at the capture anchor and `temporal`;
`TruthBundle` stores both. Sample-time poses can be reconstructed from the
descriptor and nominal request. Worker metadata and reference artifacts remain
excluded from observation-only inference. Frozen datasets and model bundles
are not modified.

## Verification and profiling

Use fresh output directories and the repository API environment for capture:

```powershell
node --experimental-strip-types tools/generate-sf10-requests.ts --learning --count 1 --output artifacts/sf13-rig/requests.json
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_GPU='1'
backend/.venv/Scripts/python.exe tools/profile-workload.py --output artifacts/sf13-rig/profile-new -- backend/.venv/Scripts/python.exe tools/validate-temporal-capture.py --requests artifacts/sf13-rig/requests.json --output artifacts/sf13-rig/acceptance-new
```

Acceptance creates six separate 100 ms scan fixtures, compares static/zero-motion
and moving repeats, validates calibration and packaging, and reloads observations
from a directory without truth or labels. The telemetry wrapper also accepts
training/inference commands, recording 100 ms NVIDIA samples and exit status.

With a PyTorch/CUDA-capable interpreter, `tools/profile-ensemble.py` measures the
unchanged hash-checked ensemble: load time, warm end-to-end p50/p95, host cProfile
and CUDA forward stream spans. Device-wide power/utilization includes other
processes. Event spans include launch gaps and are not active-kernel time.

## Remaining SF-13 work

Objects remain static during capture. This profile has constant velocity/yaw,
without pitch/roll trajectories, acceleration, exposure integration, camera
rolling shutter or timestamp-offset drift. Full sequence ordering/gaps/recovery,
trajectory/thermal replay snapshots and clip/variant split isolation remain
future work. SF-13 stays in progress.
