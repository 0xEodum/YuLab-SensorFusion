# SF-15 — Dataset scale-up and trained candidate: acceptance record

Status: all deliverables are produced. **One frozen SF-11 target is unmet** (empty-scene false positives), so SF-15 stays open until that is either revised or explicitly accepted as a reduced scope. The model card is [MODEL_CARD.md](../MODEL_CARD.md).

## Acceptance items

| Requirement | Evidence | Result |
| --- | --- | --- |
| Ladder used only when validation justifies; actual count and reason | [`selection.json`](sf15-scaling/selection.json), `validation-3000/10000.json` | 10,000 chosen: +0.183 objective over SF-Q, +0.141 over 3k. 30k not run because of the user's 10k ceiling (2026-10-23 budget extension) and the disk reserve; the curve was still rising |
| Meet SF-11 targets or document failure | `results-summary.json` → `sf11_targets` | All pass except empty-scene FP: 0.544–0.644 per empty frame against a 0.10 target. Documented in the model card |
| ≥3 training seeds, uncertainty, per-condition/class counts | `results-summary.json` | 9 seeds as 3 disjoint ensembles; mean ± SD; per-domain, per-condition and per-class positives |
| Every sensor subset, all-missing abstention | `test-report.json` | 7 subsets plus 6 corruptions; 0 detections with no sensors |
| Held-out conditions | `condition_profiles.heldout-environment` | 0.943 ± 0.027 mAP (300 frames) |
| Held-out assets | [`asset-holdout-test.json`](sf15-scaling/asset-holdout-test.json) | F-22: 0.867 ± 0.046 mAP (baseline 0.601) |
| AP / recall / localization / calibration | `results-summary.json` | See model card |
| p50/p95 latency; allocated / reserved / process memory | `inference-profile-*.json`, `training-runtime.json` | 79.7 / 93.4 ms; 19 / 31 MB GPU; 1.20 GB RSS; training peak 2.6 GiB allocated |
| No tuning on sealed test | `freeze-r2.json`, graph-crash record | Selection frozen before test. One approved re-run after an evaluator crash; 48/48 clean lines identical |
| Checkpoint load reproduces predictions | `test-report.json` | Reload parity 108/108 checkpoints |
| Temporal ablation | [`temporal-ablation.json`](sf15-scaling/temporal-ablation.json) | Descriptive, post-selection; no observed-mAP gain beyond ±0.04 |
| Model card | [MODEL_CARD.md](../MODEL_CARD.md) | Scope, synthetic limits and the unmet target |

## Commands (all exit 0 unless noted)

- **Runner resume.** `python tools/profile-workload.py --output artifacts/sf15/RUN-PROFILE-resume2 -- python tools/run-scale-experiment.py --hours 11 --max-train 10000 --extend-hours 4 --extension-authorization "2026-10-23 user: +4 h, ceiling 10k"`. Source was `4d9225e`, with the priority fix `50b089b` on disk before the freeze. It exited 1 at `sealed-test` with a CUDA illegal access; see [graph-crash](sf15-scaling/graph-crash/README.md).
- **Evaluator fix and validation recheck.** Fix in `ca31bed`. `scale-ensemble.py evaluate` for 10k and 3k validation, written to `validation-*-recheck.json`; 27,184 of 27,184 values identical.
- **Sealed test re-run.** `scale-ensemble.py freeze ... --output freeze-r2.json`, then `evaluate --split test --freeze freeze-r2.json`. See [`sealed-test-r2.json`](sf15-scaling/sealed-test-r2.json).
- **F-22 holdout.**
  - `dataset-job.py --requests requests-asset-holdout.json --workers 6`: 300 captures at 3.8 captures/s, below-normal priority.
  - `scale-ensemble.py compose --sources sources-asset-holdout.json`.
  - `freeze --dataset test-asset-holdout --training-manifest train-10000/manifest.json`.
  - `evaluate --split test --freeze freeze-asset-holdout.json --training-manifest ...`.
- **Temporal ablation.** `cache-sequence-experts.py --bundle docs/evidence/sf15-scaling/scaled-model-bundle.json --split test` on SF-13 `acceptance-run/resumed-job/dataset` and SF-14 `job-sf14/dataset`, then `score-scaled-temporal.py`.
- **Export.** `report-scale-experiment.py --freeze artifacts/sf15/freeze-r2.json` was run against the `ca31bed` evaluator, before the freeze-CLI change. Its exported freeze is stored as `freeze-r2.json`.
- **Runtime.** `profile-ensemble.py --observations artifacts/sf15/train-10000 --capture-id sf15a-1500 --repeat 200`, run for both bundles.
- **Summary.** `summarize-scale-results.py`.
- **Tests.** `python -m pytest tests/test_scaling.py tests/test_scaling_acceptance.py`: 20 passed.

## Environment

Windows 11 Pro, Python 3.13.10, PyTorch 2.13.0+cu130, RTX 3090 (driver 591.86), Edge Chromium 155 with ANGLE/NVIDIA for capture.

The resumed runner wall time was 6,875 s. During it the GPU averaged 41% utilization and 145 W, peaking at 304 W, 71 °C and 9.9 GB. Training totalled 0.73 h of CLI time across the 27 runs.

## Storage and CPU

Storage before and after the 2026-10-23 cleanup, and the priority behaviour, are recorded in [DATASET_SCALING.md](../DATASET_SCALING.md).
