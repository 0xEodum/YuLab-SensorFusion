# SF-11 learning pilot

`baseline-v1` is a diagnostic set detector for RGB, raw IR, observed LiDAR, and
simple concatenation fusion. ESSRF remains the next stage. Training and inference
are local CLI operations; this stage does not advertise a training API or UI.

## Data and boundaries

Generate `--learning` requests with `tools/generate-sf10-requests.ts`: 60 layout
seeds, 42/9/9 train/validation/test groups, 50 captures per layout, 2,100/450/450
captures. Both airfields and harbors occur in every split. All five viewpoints
and ten environmental variants of a layout stay together. Airfield fixture
layouts include open/partial/closed hangars; six layouts contain no instances.
The capture profile is 640 x 384 cameras and 32 x 256 LiDAR beams. It is synthetic,
static, and uses the existing versioned sensor/visibility policies.

`prepare` writes coverage before training: class/condition, range, visibility,
site, group and empty/ignore counts, dataset/request hashes, and leakage checks.
Test labels are counted for coverage; test observations and predictions remain
sealed until the validation-derived targets and checkpoint hashes are frozen.
There is no frame-level split. Layouts share infrastructure and mesh identities;
this is held-out layout/pose evaluation, not held-out assets or sim-to-real proof.

`learning.data.preprocess` reads only the strict ObservationBundle and its
referenced arrays. It does not open the manifest, request, annotation, truth,
instance/depth reference, ideal LiDAR, or semantic reference files. Labels enter
the separate `supervision` path and never initialize queries or compute inputs.
Calibration features exclude IDs, world origin, environment, and layout seed.

## Measured model profile

Each baseline has 16 learned queries, width 64, two decoder layers and four
attention heads. Three-layer image encoders yield 60 spatial tokens each. A point
MLP encodes 256 beam-order uniformly sampled valid observed points. A calibration
token keeps empty point scans finite. Simple fusion concatenates the three token
sets. A unimodal encoder never reads another modality's observations.

Preprocessing is fixed as `baseline-preprocess.v1`: area-resize cameras to
160 x 96; sRGB divided by 255; linear IR radiance divided by 100, invalid pixels
zeroed; observed LiDAR transformed by nominal extrinsics to world axes relative
to rig origin, divided by 200 metres, with observed intensity. No per-image
contrast normalization or oracle crops are used. Checkpoints include this exact
profile and the dataset hash. Raw captures retain their original resolution.

Heads predict class/no-object, relative centre XYZ, positive extent XYZ and yaw.
Only upright boxes are supported; non-yaw labels fail explicitly. The current
capture labels are posed world-axis bounds with identity rotation. A set loss
uses Hungarian assignment from predicted classes/centres/extents, cross-entropy
with no-object weight .15, centre L1 weight 8, log-extent L1 weight .5 and yaw
cosine weight .2. Matching/loss can access labels; the model cannot.

Default budget: seed 11, FP32, AdamW, learning rate .001, weight decay .0001,
gradient clipping 1, batch 32, 40 epochs for every baseline. Deterministic
algorithms are enabled; no cross-driver bitwise guarantee is made. Tiny training
uses selected train-only positives of all three classes plus an empty frame and
requires mAP >= .90. Loss histories include validation metrics. Best checkpoints
are chosen by validation 3D mAP. Test runs verify the frozen checkpoint hashes.

## Evaluation and output

The independent evaluator clips oriented ground rectangles and intersects vertical
intervals for exact upright 3D IoU. Score-ranked, one-to-one same-class matching
uses aircraft/ground-vehicle IoU .25 and ship IoU .50. AP integrates the precision
envelope over recall. Classes without positives are explicitly unevaluable.
Fully hidden discoveries, wrong classes and duplicates count as false positives;
geometrically eligible objects remain positives under corruption. Reports include
AP, recall, matched centre error, detection ECE in ten bins, per-condition counts,
empty-scene false positives, loss curves, runtime and allocated/reserved/process
memory. Confidence is softmax, without post-hoc calibration. Variance and
evidential routing are absent; PredictionBundle marks them null.

`freeze` records explicit SF-15 class/condition AP targets from validation, with
absolute floors .50/.35, a .05 margin above the best observed baseline, and .95
ceiling. It also records recall >= .70, matched centre error <=5 m, empty-scene
FP/frame <=.10, ECE <=.15, p95 inference <=500 ms and training allocation <=18 GiB.
These are future candidate acceptance targets, not claims that baselines meet them.

The initial SF-11 head is 3D only. Visible 2D masks remain dataset supervision;
visible 2D AP is a subsequent detector/evaluation extension and is not claimed
here. Temporal state, sensor-subset routing, trained reliability, uncertainty,
held-out asset evaluation and interactive inference remain later stages.

## Reproduction

The hash-locked learning environment targets measured Windows CPython 3.13,
official PyTorch CUDA 13.0 wheels. CPU execution is supported by the model on
that environment. A different OS/wheel requires its own pinned environment.
Backend service dependencies remain unchanged.

The current machine's fresh environment download timed out. Actual acceptance
runs use its existing CPython/PyTorch installation; the exact installed versions
and executable are recorded with the evidence. The optional lock remains the
fresh-install recipe; fresh installation has not yet passed on this machine.

```powershell
$env:UV_CACHE_DIR=(Join-Path $PWD 'artifacts/sf11/uv-cache')
$env:UV_PROJECT_ENVIRONMENT=(Join-Path $PWD 'backend/.venv-learning')
node tools/uv.mjs sync --project backend/learning-env --locked
New-Item -ItemType Directory -Force artifacts/sf11 | Out-Null
node --experimental-strip-types tools/generate-sf10-requests.ts --learning --output artifacts/sf11/requests.json
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:YULAB_CAPTURE_ROOT=(Join-Path $PWD 'artifacts/sf11/captures')
backend/.venv/Scripts/python.exe tools/dataset-job.py --requests artifacts/sf11/requests.json --output artifacts/sf11/pilot-3000 --dataset-id sf11-learning-v1 --workers 6
backend/.venv/Scripts/python.exe tools/dataset-job.py --requests artifacts/sf11/requests.json --output artifacts/sf11/pilot-3000 --validate --workers 6
backend/.venv-learning/Scripts/python.exe tools/learning-pilot.py prepare
backend/.venv-learning/Scripts/python.exe tools/learning-pilot.py tiny
backend/.venv-learning/Scripts/python.exe tools/learning-pilot.py train
backend/.venv-learning/Scripts/python.exe tools/learning-pilot.py freeze
backend/.venv-learning/Scripts/python.exe tools/learning-pilot.py test
$env:PYTHONPATH='backend'
backend/.venv-learning/Scripts/python.exe -m pytest backend/tests/test_learning.py
```

Add `--resume` after interrupted collection. The atomic publisher retries only
transient PermissionError within a bounded two-second sharing window; permanent
errors still fail. Datasets/caches/checkpoints remain ignored local artifacts.
