# SF-11 learning pilot acceptance record

Date: 2026-10-01. Status: **IN PROGRESS**; held-out baseline acceptance pending.

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

## Outstanding acceptance

The 2026-10-02 resource-utilization follow-up is recorded separately in
[SF-11 performance](SF-11-performance.md). Optimized runs use separate directories;
the original frozen runs and test reports are preserved. The performance gate
checks train/validation only and does not reopen the sealed test for tuning.

Complete the independent label audit, equal-budget unimodal/simple-fusion runs,
validation selection, SF-15 targets freeze before test observations, sealed-test
reports, checkpoint prediction replay, observation-only inference with labels and
truth absent, curves and artifact hashes. SF-11 stays IN PROGRESS until these pass.
