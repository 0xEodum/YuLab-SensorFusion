# SF-11 learning pilot acceptance record

Date: 2026-10-01; closed 2026-10-02. Status: **DONE** (local acceptance).

The task began from clean `main` revision
`2fc8faf0c440978a6f11e3dbcd095d37bf421c6a`. No hosted workflows were run.
The [implementation profile](../LEARNING_BASELINES.md) defines preprocessing,
model, training budget, metric semantics, test seal and remaining scope.

## Dataset checkpoint

`node --experimental-strip-types tools/generate-sf10-requests.ts --learning
--output artifacts/sf11/requests.json` generated 3,000 requests (exit 0).
Request SHA-256: `3eb4fca6c9627bed5c4febf00c746a2a67fe650541a57afe5f65de73af0a5047`.
The dataset uses 640 x 384 cameras and 32 x 256 LiDAR, 60 layout groups,
2,100/450/450 train/validation/test captures, and both sites in each split.

The six-session Edge collection produced all 3,000 frames. Windows sharing errors
interrupted directory/state publication; an existing bounded two-second retry
now also covers those atomic renames. Resume additionally exposed a missing
sequence ID in reconstructed capture entries; resume now restores and checks it.
Permanent sharing errors still fail explicitly. All complete frames were reused
during final publication. No partial directory is treated as a complete capture.

The final complete job succeeded (exit 0), including every hash/shape/schema check.
Manifest SHA-256: `00f167a9d263410b783c45f5282a78df8643e28319308a03d891db4521179e3f`.
Size: 25,499,253,783 bytes, approximately 8.50 MB/capture. The final resume/readback
elapsed 548.50 s; it reused 3,000 captures, so its rate is **validation/publication
throughput**, not new-sample generation throughput. Original attempt and resume
logs remain under `artifacts/sf11/`.

`python tools/learning-pilot.py prepare` wrote class/condition, range, visibility,
site/group and ignore counts before training and verified layout, sequence,
weather-variant and observation-duplicate isolation. Train/validation/test have
280/80/60 empty-positive frames and 200/50/50 background-only frames. Strata with
fewer than five independent positive groups are explicitly marked underrepresented.
Test observations are not cached or inferred during preparation/training.

## Implementation checkpoint verification

- `npm run verify`: exit 0, generated-contract drift, TypeScript, shared contracts,
  world/sensor/asset/backend suites, and production build passed. Backend skips
  the optional learning module when PyTorch is absent from its service environment.
- `PYTHONPATH=backend OMP_NUM_THREADS=2 python -m pytest
  backend/tests/test_learning.py backend/tests/test_capture_lanes.py -q`: exit 0,
  13 passed. Independent cases cover rotated IoU with analytically known volume,
  score-ranked AP with duplicate and hidden discoveries, permutation matching,
  wrong-box loss, empty loss/backward, empty observed scans, unimodal isolation,
  truth-free preprocessing, sequence restoration and bounded sharing retries.
- Initial learning test collection failed because the module did not exist (RED).
  CUDA deterministic mode subsequently rejected adaptive pooling backward;
  fixed 2 x 2 average pooling preserves the documented 60-token shape and passes.
- `python tools/learning-pilot.py tiny`: exit 0, 1,200 updates over seven train-only
  captures, 14 eligible objects across all classes and one empty frame. 3D mAP,
  each class AP and recall = 1.0; zero false positives; matched centre error 1.99 m.
  Elapsed 55.08 s; peak GPU allocated/reserved 740,597,760/761,266,176 bytes.
  This is an overfit/consistency check, not held-out quality.

The optional environment is source-pinned and hash-locked under
`backend/learning-env/`. Fresh wheel downloads timed out, including unrelated
small wheels, and a first mixed-index requirements attempt failed its hash check.
The final explicit PyTorch index resolves successfully but fresh installation
remains unverified. Actual learning runs use the installed Windows CPython
3.13.10, PyTorch 2.13.0+cu130, NumPy 2.4.2, SciPy 1.17.1 on RTX 3090/24 GB.
Exact installed versions are retained in `artifacts/sf11/measured-environment.json`
and will accompany final evidence. This limitation is not hidden by the lockfile.

## Held-out acceptance

The 2026-10-02 resource-utilization follow-up is recorded separately in
[SF-11 performance](SF-11-performance.md). Optimized runs use separate directories;
the frozen 2026-10-01 runs below are the canonical SF-11 results. The closing
review on 2026-10-02 re-hashed them; no model was retrained or re-evaluated.

| Gate | Evidence | Result |
| --- | --- | --- |
| Independent label audit | `tools/audit-sf10-pilot.py` over all 3,000 captures (`artifacts/sf11/independent-audit-final.log`, `pilot-audit.json`) | Pass: 4,610 eligible/8,690 ignored objects, equal geometry hashes across 300 condition-variant sequences, 42/9/9 train/validation/test layout groups with both sites in each split. An earlier parallel attempt stopped on a request rig-hash mismatch and was superseded by this run. |
| Equal-budget baselines | `sf11/<model>-history.json`, `-runtime.json` | All four models: 40 epochs, same train/validation groups, one seed; 0.75–0.85 GB peak GPU allocation. |
| Validation selection | `best_validation_ap` epoch per model | Selected on validation only. |
| SF-15 targets frozen first | Commit `656e99c` (14:40:41); first sealed-test log 14:46:59 | `sf15-targets.json` unchanged since that commit. |
| Sealed-test reports | `sf11/<model>-test.json` | Recorded below; no tuning followed test access. |
| Checkpoint prediction replay | `checkpoint_reload_exact_prediction_parity` | True for all four; checkpoint and test-prediction SHA-256 values match `sf11/artifact-manifest.json`. |
| Observation-only inference | `artifacts/sf11/inference-isolated/` (12 observation files, no truth/annotation) | Identical detections for all four models. |
| Curves and hashes | `sf11/learning-curves.png`, `artifact-manifest.json` | Present; dataset SHA-256 `00f167a9…179e3f`. |

### Results

3D mAP; class AP uses IoU 0.25 for aircraft/ground vehicle and 0.5 for ships.
Validation positives are aircraft 350/ground vehicle 140/ship 180; test positives
are 320/150/240.

| Model | Val mAP | Test mAP | Test AP air/ground/ship | Test centre error | Test ECE | Empty-scene FP (60 test) | p95 batch-1 ms |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| RGB | 0.287 | 0.369 | 0.269 / 0.346 / 0.492 | 4.41 m | 0.442 | 22 | 5.57 |
| **IR** | **0.387** | **0.476** | 0.313 / 0.297 / 0.819 | 5.26 m | 0.348 | 10 | 5.37 |
| LiDAR | 0.288 | 0.366 | 0.067 / 0.300 / 0.730 | 5.64 m | 0.512 | 101 | 4.48 |
| Simple fusion | 0.309 | 0.393 | 0.384 / 0.018 / 0.779 | 5.44 m | 0.435 | 29 | 6.47 |

Findings:

- **IR-only is the strongest baseline** on validation and test, so SF-12 should
  compare against IR-only as well as simple fusion. Beating simple fusion alone
  is not enough.
- **Simple fusion does not beat the best single modality.** It has the best
  aircraft AP, but its ground-vehicle result is unstable: 0.271 AP on validation,
  0.018 on test. The likely causes are a single seed, few independent
  ground-vehicle layout groups and concatenation without any reliability
  weighting. This is the gap that ESSRF's reliability and subset routing target.
- Every baseline is below the frozen SF-15 targets: class AP ≥ 0.5 (ship ≈ 0.76),
  recall ≥ 0.7, centre error ≤ 5 m, empty-scene FP ≤ 0.1 per frame and
  ECE ≤ 0.15. Confidence is uncalibrated softmax (ECE 0.35–0.51).
- Test mAP is higher than validation mAP for every model. The test layouts appear
  easier rather than the result being tuned, but the difference shows how much
  noise a 15-layout split carries.

### Limits

One training seed; static synthetic scenes with shared meshes; 3D-only heads.
Fresh installation of the hash-locked environment remains unverified. Runs used
the recorded installed environment. Resident latency excludes observation
readback; isolated end-to-end example timings are 24–112 ms. The sealed test
has now been observed once and must not be used to select SF-12 profiles.
