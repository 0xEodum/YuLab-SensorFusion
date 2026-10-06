# SF-12 curriculum and paired degradation TDD (2026-10-06)

Journeys derive from the user's request: preserve clean controls while making the
mixture train throughout a gradual curriculum; compare frozen baselines and ESSRF
on the same degraded validation observations; preserve truth-free inputs and failures.

| Guarantee | RED evidence / checkpoint | GREEN evidence |
| --- | --- | --- |
| Q16 default; mixture from epoch one; monotone 8+16 ramp; exact 70% full sensors; eligible final-regime checkpoint | `test_essrf_curriculum.py`: 9 intended failures, `1cda700` | 33 tests passed with existing ESSRF acceptance; `7f437da` |
| Same raw corruption before both profiles; copy isolation; deterministic noise; all eight availability cases | `test_sensor_degradation.py`: missing helpers/module | 14 degradation/comparison tests passed; `d8067d7`, `5a05abf` |
| AUROC ties count half | Equal vacuity scores produced 0.0 rather than 0.5; same RED suite, `6eb32a2` | All tie assertions pass; `d8067d7` |
| Cache/checkpoint provenance; unchanged calibration; measured baseline hallucinations; validation-only preparation | `test_sf12_comparison.py`: 4 intended failures, `1d567a0` | Complete prepare/evaluate integration, both model profiles and all 14 cases; `fc824b8` |

Executed RED commands:

```
python -m pytest backend/tests/test_essrf_curriculum.py -q
python -m pytest backend/tests/test_sensor_degradation.py -q
python -m pytest backend/tests/test_sf12_comparison.py -q
```

Full learning GREEN command (69 passed):

```
python -m coverage run --source=backend/learning -m pytest backend/tests/test_essrf.py backend/tests/test_essrf_curriculum.py backend/tests/test_sensor_degradation.py backend/tests/test_sf12_comparison.py backend/tests/test_learning.py -q
```

The actual invocation additionally listed `tools/essrf-pilot.py` as a coverage
source, which coverage warned is a path rather than an importable module; this
did not affect backend coverage or test results. Coverage data lives locally in
`artifacts/sf12/tdd.coverage`.

Measured coverage across the changed backend files: **82%** (662 statements,
120 uncovered). New raw degradation: 100%; comparison runner: 93%; curriculum
training: 87%. Preprocessing coverage includes pre-existing supervision branches
outside this change (baseline 77%, ESSRF 64%). Evaluation is 70%; the legacy
standalone evaluator and some calibration branches remain uncovered by this run.
CUDA training convergence is experimental evidence, not a unit-test assertion;
the CPU integration verifies schedule application, actual epoch counters,
optimizer-update budget, eligible selection and checkpoint reload.

Only local validation is used. Static frame-wise scope remains; no temporal or
calibration-uncertainty claims, and no new access to the sealed test split.

## Additional diagnosed issues and final verification

- The working global learning Python lacked the project's pinned
  `rfc3339-validator==0.1.4`. Consequently jsonschema had no date-time checker and
  the pre-existing bad-timestamp test failed. Installing the declared dependency
  repaired the environment; no payload-validation code was weakened.
- The original CUDA image sampler's forward repeated exactly, but its gradients
  differed by up to 1.502e-5 at identical inputs/weights. Deterministic mode
  rejected `cudnn_grid_sampler_backward`. `test_essrf_sampling.py` reproduced
  this and the absent replacement: four RED tests (`f7ed9dc`).
- `bilinear-v1` uses align-corners, zero-padding bilinear interpolation with
  deterministic gather gradients. CPU float64/float32 values and both feature
  and coordinate gradients match the reference within 1e-12 / 2e-6 respectively.
  Complete CUDA model forward/backward repeats exactly. Sampler/config/numerical
  provenance regressions contributed two additional RED failures (`fcfbfca`),
  fixed at `35d9310`. Legacy checkpoints retain their original grid sampler.
- Full-data replay at `f0b47be`: two independent two-epoch runs, with one clean
  epoch and one final-regime epoch, gave **identical histories, all model tensors
  and AdamW state**. Both used 2,100 train and 450 validation captures. The
  result is `docs/evidence/sf12/reproducibility.json` once published.
- Ungated surviving-subset expert scores and evaluation-device provenance are
  now reported to diagnose routing versus detection weakness. One RED
  integration assertion (`08c308a`) became GREEN at `f0b47be`.

Final validation command:

```
# COVERAGE_FILE=artifacts/sf12/tdd-final.coverage
python -m coverage run --source=backend/learning -m pytest backend/tests -q
```

**201 passed**. Changed learning-file coverage is **87%** (951 statements, 121
uncovered): model 99%, curriculum 87%, shared corruption 100%, comparison 93%.
Pre-existing supervision/standalone-evaluation gaps listed above remain.
`npm run verify` also passed (contracts, TypeScript checks, world/sensor/asset
tests, locked backend tests and production build). Its locked backend run skips
the learning tests, which are independently exercised by the command above.

The initial Q16 default was subsequently superseded by measured selection of
Q32: paired-degradation macro .062 versus .177, seed 11, identical repaired
sampler/curriculum/budget. Public model and CLI defaults follow that choice,
while `--queries 16` remains supported. This behavioral revision had one RED
default assertion (`3a05656`), followed by 16 passing curriculum/sampling tests.
The final configuration is fixed before training seeds 12/13.

The post-export artifact audit also checked committed Git blobs, rather than
only working-tree files. Windows text normalization made 24 committed evidence
hashes differ from the raw-byte manifest (RED at `b72cd3e`). Marking the SF-12
artifact directory `-text` in `.gitattributes` and restaging its original bytes
repairs this packaging issue; all 28 manifest entries match the staged blobs.
This preserves the existing evidence-directory convention across platforms.
