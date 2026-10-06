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
