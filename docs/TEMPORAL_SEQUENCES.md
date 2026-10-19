# Temporal object capture and sequence replay

SF-13 extends the existing `rig-motion-drift.v1` capture profile with optional
`object_motion` and adds canonical `SequenceSpec`, profile `temporal-sequence.v1`.
Commands remain local. The capture API accepts moving-object requests; sequence
collection/recovery uses the CLI below. Temporal detector training is SF-14.

## Object and sensor time

`CaptureRequest.world` is the immutable generation/reference snapshot. Each
moving instance's transform is its pose at `temporal.reference_time_s`. At sample
time `s`, its origin advances by `velocity_world_m_per_s * (s-reference_time_s)`;
world +Y yaw rotates its orientation around its own origin. Motion requires
rigid transforms and existing unique instance IDs. Nonmoving objects retain
their reference pose. The original static path is unchanged.

Platform nominal pose remains anchored at the current capture tick, as in
[rig motion](TEMPORAL_CAPTURE.md). Sensor drift uses absolute reference time.
These clocks are explicit: world object poses are reference-time snapshots;
nominal platform poses are current-frame snapshots.

Each camera renders object geometry and visibility at its own timestamp.
IR uses the evolved thermal state at its sample time; the saved thermal artifact
remains at the frame anchor for continuation. LiDAR intersects each object at
beam emission time. One immutable BVH per moving instance is retained through
the scan: the ray is transformed into its anchor-world frame, then the first
hit and normal are transformed back. Triangle BVHs are not rebuilt per beam.
Fixed geometry wins exact temporal ties, then sorted moving instance ID.

Moving objects are retained even if their reference pose lies outside the
current site-culling region. Amodal boxes and actual `TruthBundle.objects`
poses/velocities are recorded at the capture anchor. RGB/IR masks and LiDAR
hit counts use their own sample times. `TruthBundle.world` retains the reference
snapshot, and its temporal descriptor reconstructs the sample-time geometry.
Detection boxes retain the existing posed world-axis bounds and identity box
quaternion; the actual object's rotation is recorded in its truth transform.

## Frozen sequence specification

A `SequenceSpec` contains a base capture template, sequence/family/variant/group
IDs, split, start time, frame interval and count, outage windows and ordered
operating-state events. Frame requests bind fresh world/nominal-rig/environment
hashes and IDs. The base template is not submitted directly.

The sampling grid is contiguous and fixed. Negative sensor offsets, overlapping
acquisition windows across frames, duplicate events, frame gaps, duplicates,
timestamp disorder and changed resume specifications fail explicitly. The first
frame initializes thermal equilibrium. Later frames reference the exact previous
published thermal artifact, including when all observed sensors are absent.

All variants of a family must share physical scene, nominal trajectory and
sampling grid. Weather, sensor drift and outages may vary. Family, layout group
and reference scene cannot cross splits. Manifest validation checks every
sequence's complete ordered replay chain before publishing the manifest.
Repeated observations inside a temporal family are permitted; all-missing frames
are expected. This does not permit family/group leakage across splits.

## Durable execution and recovery

Each job owns one local output directory. An OS-managed SQLite write lock
prevents concurrent coordinators for that directory and releases on process
death. This is a local filesystem design, not a network-shared SQLite service.

A frame is packaged and checked under `.partial`, with `sequence_state_json`
containing its frozen specification/request hashes, predecessor snapshot hash,
frame index/time, nominal/actual rig, actual objects, thermal artifact and outage
state. Atomic directory rename publishes the complete frame. The progress file
stores compact inventory/snapshot hashes and is replaced atomically afterward.
A crash between frame publication and progress update can recover that frame
from its checked snapshot. Missing or modified published frames are errors.

On resume, completed frames form an immutable contiguous prefix. A fresh worker
cache is supported: the predecessor thermal artifact is hash-checked and restored
from the published frame. Geometry/asset caches are disposable. Replay derives
object, platform, calibration and RNG state from the frozen specification.
A completed job validates its manifest without rewriting it.

Outages represent loss of delivered observations. The simulator still captures
reference geometry and thermal history. Observation entries become explicitly
unavailable and their sensor flags turn off; no absent sensor arrays are read by
the inference loader. Geometry-derived labels remain unchanged. Observable
`frame_index` and `capture_time_s` support timing even during a full outage.
Motion/drift/actual-state/family truth never enters ObservationBundle.

## Commands

Use fresh paths for generation and new jobs, and the repository API environment:

```powershell
backend/.venv/Scripts/python.exe tools/generate-sequences.py --output artifacts/sf13-sequences/specs-new.json
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_GPU='1'
backend/.venv/Scripts/python.exe tools/sequence-job.py --specs artifacts/sf13-sequences/specs-new.json --output artifacts/sf13-sequences/job-new --stop-after 8
backend/.venv/Scripts/python.exe tools/sequence-job.py --specs artifacts/sf13-sequences/specs-new.json --output artifacts/sf13-sequences/job-new --resume --worker-cache artifacts/sf13-sequences/worker-new
backend/.venv/Scripts/python.exe tools/sequence-job.py --specs artifacts/sf13-sequences/specs-new.json --output artifacts/sf13-sequences/job-new --validate
```

`--stop-after` is a controlled recovery probe; Ctrl+C requests cooperative
cancellation. Defaults generate three independent layouts, each with clean and
drift/outage variants: 192 captures, 32 frames per 6.2 s clip, 640x384 RGB/IR and
32x256 LiDAR beams. Individual sensor outages last four frames; the full outage
lasts six frames and is followed by four recovery frames. Validation/test layouts
are new synthetic layouts, not a real-world generalization result.

For real-worker acceptance and device-wide GPU telemetry:

```powershell
backend/.venv/Scripts/python.exe tools/profile-workload.py --output artifacts/sf13-sequences/profile-new -- backend/.venv/Scripts/python.exe tools/validate-sequences.py --specs artifacts/sf13-sequences/specs-new.json --output artifacts/sf13-sequences/acceptance-new
```

The acceptance harness deliberately stops/restarts collection with a cold cache,
compares a complete clip against uninterrupted replay, checks a frozen-anchor
camera control, and validates split/observation isolation. Its own `--resume`
continues an interrupted acceptance run using saved stage records.

## Scope

This is a synthetic constant-linear-velocity/yaw, global-shutter profile.
Pitch/roll trajectories, acceleration, exposure integration, rolling shutter,
calibration timestamp drift and empirically calibrated temporal sensor noise
remain extensions. The pilot retains fixed base RNG channels across its frames
as a reproducible fixed-pattern control. It is not evidence of learned temporal
robustness or independent real sensor noise. Static SF-Q datasets/weights remain
frozen; scaling and temporal model quality have separate acceptance stages.
