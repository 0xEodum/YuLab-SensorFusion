# SF-13: temporal object capture, outages and durable replay

Accepted 2026-10-19 on `feature/temporal-object-trajectories-sequence-replay`.
SF-13 is DONE; SF-14 is the next separate temporal-detector stage. This report
closes capture/dataset acceptance, without promoting a learned temporal model.

Main implementation: `0d05a13abf940945b8a4affa9386ec89592245ff`.
Final behavioral fixes: `6f75b9f` (scene split identity independent of world label)
and `924ff87` (reject unsupported pre-anchor thermal samples). The full capture
acceptance ran on clean `0d05a13`; the dataset was independently revalidated
after the split fix. Final regression includes both fixes.

## Delivered behavior and contracts

- Optional object trajectories use reference-time world poses, constant world
  velocity and world +Y yaw. Cameras sample geometry/labels at their timestamp;
  LiDAR intersects moving geometry at every beam's emission time.
- Static and per-object immutable BVHs avoid per-beam triangle rebuilds. Analytic
  wall controls and independently posed brute-force raycasts verify motion and
  occlusion, including a foreground object moving out of the line of sight.
- Canonical `SequenceSpec` freezes clip/family/variant/group IDs, split, sampling
  grid, operating events and outages. Nominal platform and actual object/sensor
  states remain separate. Only frame index/time and sensor availability enter
  ObservationBundle; motion/drift/actual poses remain truth.
- Ordered per-frame snapshots contain request/spec hashes, predecessor hash,
  thermal reference and nominal/actual states. Atomic directory publication and
  compact progress hashes support cold-cache resume and recovery of a frame
  published before its journal update. An OS-managed local SQLite write lock
  prevents concurrent coordinators for one output directory.
- Family, layout group and reference scene cannot cross splits. A world label
  rename cannot disguise a copied scene. Frames with gaps, duplicates, timestamp
  disorder, corrupt inventories or changed resume specifications fail explicitly.

The [sequence profile](../TEMPORAL_SEQUENCES.md) defines units, time anchors,
outage semantics, commands and restrictions. Generated TS/Python bindings and
shared fixtures derive from the canonical JSON Schema; no hosted workflow ran.

## Acceptance data and accounting

The pilot contains **192 captures: six clips of 32 frames**, with three independent
layout groups (airfield/harbor/airfield). Each group has paired clean and
drift/outage variants; splits contain 64 train, 64 validation and 64 test captures.
Each clip spans 6.2 s at 0.2 s intervals. Cameras retain 640x384 resolution and
LiDAR 32x256 beams with a 100 ms scan. The published dataset occupies
1,693,228,139 bytes, including its manifest and replay snapshots.

Individual sensor outages last four frames. Each adverse clip has six frames of
all-sensor outage followed by four recovery frames: **18 all-missing frames** in
the pilot. Simulator thermal history and geometric labels continue during lost
observations. Model loaders do not read arrays from unavailable observations.

- Specification composite SHA256: `12dab8fd52aa44ac4ebffd7b45d4838fa8b01a56914a5bb5e797dd53d33cdf2c`.
- Dataset manifest SHA256: `e6a46b45bb24cfc87d8ff776c96c6fb28b63b8deaf1c02ac66a2c2aa983b034b`.
- Dataset source revision: `0d05a13abf940945b8a4affa9386ec89592245ff`.
- Local dataset: `artifacts/sf13-sequences/acceptance-run/resumed-job/dataset`.

Datasets/checkpoints remain ignored local artifacts. Frozen SF-11/SF-Q datasets,
weights, preprocessing and historical quality evidence were not modified.

## Tests and reproducibility

| Guarantee | Check and measured result |
| --- | --- |
| Beam-time translation/rotation matches physical geometry | Six object-motion tests: analytical wall ranges, independent brute-force poses, static parity, dynamic occlusion, invalid motion, analytical camera registration error |
| Cold recovery preserves published prefix | Controlled stop after eight frames; a new process and empty worker cache resumed 184 new frames; all 336 published prefix files unchanged |
| Interrupted and uninterrupted clips agree | 32-frame independent replay: **1,312 byte-identical files**, excluding only performance-bearing worker metadata |
| Camera geometry and labels match the actual anchor scene | Frozen-object last-frame control: eight raw camera/reference/thermal artifacts match exactly; every posed 3D box matches within 1e-7 |
| Actual transforms are checked independently | Object transform maximum error 0; drift translation maximum error 2.78e-17 m |
| Thermal history evolves and replays | Maximum surface-temperature change 1.2383 K after operating-state transition; exact replay includes thermal files |
| Published frame survives missing journal update | Simulated `running` journal with frame 1 already published but only frame 0 recorded; cold recovery reused two/new two frames; 164 replay files match |
| Corruption and disorder are rejected | Modified replay snapshot rejected as corrupt inventory; reordered manifest rejected; original data unchanged |
| Observation-only model compatibility | Export contains no labels, truth or replay metadata; unchanged hash-checked ensemble runs on it; all-missing frame emits zero detections |
| Static rig capture remains byte-compatible | Six-capture rig-motion acceptance rerun: static repeat/zero-motion and moving repeat match exactly |
| Complete backend suite | **244 passed**, no skips, `PYTHONPATH=backend; python -m pytest backend/tests -q` |
| Core verification | `npm run verify`: exit 0; 79 contract, 24 world, 41 sensor, 10 asset tests; 162 API-environment backend tests pass and 8 ML modules skip there; production build passes |
| Production UI regression | Edge/NVIDIA GPU: seven backend/capture/cancellation/browser-closure/weather/thermal checks pass |

Targeted coverage including unit tests and real capture: sequence coordinator 84%,
sequence semantics 90%, temporal Python boundary 89% (87% combined statements).
Object-motion TypeScript targeted tests cover 98.08% lines. This is not a
whole-project coverage claim. Preview inspection confirms visible object motion.

RED/GREEN history is preserved: `b7c93fc` introduced executed tests failing on
missing object-motion/sequence modules; `0d05a13` supplied implementation. Review
found the world-ID split alias (`61970ec` RED, `6f75b9f` GREEN), then unsupported
negative IR offsets (`1166db4` RED, `924ff87` GREEN). The latter is rejected rather
than silently rendering a sample using a later saved thermal state.

## GPU and end-to-end performance

Measured RTX 3090, driver 591.86, 370 W power limit, Python 3.13.10, native NVIDIA
D3D11 rendering in Edge. The API environment performs capture; the existing
PyTorch 2.13.0+cu130 interpreter runs model compatibility/full backend checks.
No unrelated process was stopped. NVIDIA metrics are device-wide under shared
desktop load, not per-process attribution or active-kernel timings.

| Phase | Wall time | Average GPU / power | Peak power |
| --- | ---: | ---: | ---: |
| First eight frames and controlled stop | 20.96 s | 7.72% / 79.25 W | 118.29 W |
| Cold resume: 184 new + eight checked existing frames, final validation/publication | 431.23 s | 12.00% / 51.48 W | 143.04 W |
| Validate completed 192-frame job without rewriting manifest | 52.21 s | 3.66% / 36.58 W | 38.76 W |
| Independent 32-frame uninterrupted replay | 70.88 s | 7.68% / 75.84 W | 139.19 W |

The entire acceptance harness, including separate audits/replay/control, took
637.46 s and collected 5,828 telemetry samples: mean 9.92% GPU, 52.96 W, 49.41 C;
maximum temperature 53 C. The cold-resume stage yields about .427 new captures/s,
including predecessor checks and final validation. This is a correctness-first
single-coordinator baseline, not a concurrent capture throughput benchmark.

Across 192 worker captures, mean/median Node elapsed time was 1071/856 ms. Median
browser phases: meshing .2 ms (cold max 3309 ms), RGB/reference 284 ms, visibility
119 ms, thermal 47 ms, LiDAR build 11.5 ms, LiDAR scan 44 ms, previews 17 ms.
Operating-state template changes also invalidate the complete world snapshot
cache; their cold meshing costs remain visible. File hashes, JSON Schema, snapshot
checks, readback/encoding/publication and repeated manifest validation add host
work outside those browser phases.

The user's >300 W / about 70 C working reference was **not reached**. Low power
is consistent with substantial CPU/I/O/validation work and intermittent graphics
bursts. It does not prove GPU saturation or thermal limiting. Training was not
run. Independent-family concurrency and eliminating redundant validated reads
are candidates for a separate measured optimization, preserving exact files,
replay and split invariants. No performance default was promoted here.

## Provenance and limits

Published [evidence manifest](sf13-sequences/artifact-manifest.json) hashes the
specifications, acceptance/audit records, raw telemetry, logs and preview frames.
The source manifest identifies exact implementation Git blobs. PowerShell UTF-16
logs are transcribed to UTF-8 for publication; hashes identify published bytes.
Final tests use `924ff87`; no motion/capture behavior changed after that checkpoint.
Post-collection fixes only tighten copied-scene split validation and reject an
unsupported negative thermal offset; collected pilot offsets are nonnegative.

This is synthetic constant linear/yaw motion with global shutters, the existing
first-return sensor response and world-axis detection boxes. It does not establish
real motion realism, acceleration/pitch/roll/rolling shutter, unseen faults,
sim-to-real performance or learned temporal robustness. Frame RNG channels stay
fixed as a reproducible fixed-pattern control. The pilot has only three independent
layouts and is capture acceptance, not a final temporal training/quality benchmark.
