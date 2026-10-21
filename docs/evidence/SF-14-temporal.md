# SF-14: temporal tracker over the frozen static ensemble (2026-10-21)

Branch `feature/temporal-tracker-static-ensemble`. Protocol, validation trace and the single test report are in
[sf14-temporal](sf14-temporal/). Profile: [`ensemble-kalman-tracker.v1`](../TEMPORAL_TRACKER.md).

## Decision

`essrf-temporal-v1` was **not** trained. Reasons, all measured earlier: static ESSRF failed to train on 2,100
captures (SF-12), the SF-Q frozen ensemble is the strongest detector, and the SF-13 pilot supplies only a few
clips. A learned temporal head would be fitted to almost no sequences. The backlog allows replacing the proposal
with documented evidence; ESSRF.md carries the decision entry. The SF-Q weights, preprocessing and bundle are
unchanged (ensemble SHA256 `fbe84065...f17b56`).

## Result (test split, scored once)

Six test clips from three new layouts (SF-13 `airfield-825838`; SF-14 `airfield-1825838`, `harbor-1849595`),
observed-detection mAP with the unchanged SF-Q evaluator, matched frames, identical splits:

| | Static ensemble | Temporal tracker |
| --- | --- | --- |
| Clean 3D mAP | 0.7402 | 0.7449 |
| Degradation macro (6 subsets + 6 corruption probes) | 0.7288 | 0.7388 |
| Combined (selection metric) | 0.7345 | 0.7419 |
| Scenarios where tracker mAP > static | | 12 of 13 |
| False positives, clean | 261 | 82 |
| False positives, ir-ood | 1261 | 496 |

The gain is small (+0.005 clean, +0.010 macro) and rests on three test layouts and six clips; it is not a
confidence-interval claim. The sizeable, consistent effect is false-positive reduction (about 2-3x in most
scenarios) with unchanged recall (available-frame recall 0.88-0.89 for both). Clean-frame recall did not improve.

Outage behaviour (all sensors absent, 6-frame windows in drift/outage clips):

- Static ensemble: zero detections by construction (recall 0.0).
- Tracker: prediction-only continuation recall 0.83-0.88 at mean centre error 4.2-5.5 m (objects are 25-180 m
  long; the class IoU thresholds still hold). These boxes are flagged `observed = False` and are excluded from
  the observed mAP above; `tracker_with_prediction_only` is reported separately in the test report.
- Invented observations: **0** across all 13 scenarios (observed outputs or newly born tracks during any
  all-sensor outage).
- Recovery after an outage: 6 of 8 object events recovered in the clean scenario for both methods, with mean
  latency 1 frame. The tracker does not recover faster than the static ensemble; the two unrecovered events
  are not recovered by either.

Cost: tracker step p50 0.7-3.4 ms, p95 1.4-7.6 ms (CPU, includes association); tracemalloc peak 0.51 MB over a
32-frame clip. The ensemble itself is unchanged (SF-Q: 109 ms median including loading and fusion). Producing the
per-sensor cache took 220 s for 384 frames x 13 scenarios (0.044 s per frame-scenario).

## Protocol and integrity

- Data: SF-13 pilot (192 captures, 3 layouts, 0.5 m/s target) plus a new SF-14 set (384 captures, 6 layouts,
  3 m/s target) generated with `tools/generate-sequences.py --layouts 6 --seed-offset 1700000 --prefix sf14
  --object-speed 3`. SF-14 splits: 2 train, 2 validation, 2 test layouts. No layout group appears in SF-11, SF-Q
  or across splits (checked against the SF-11 and SF-Q manifests).
- Dataset manifest SHA256 (SF-14): `addaf1a5c06184b96ae14224dcd45587c8b35800c428428b01153a43a8e5f92f`;
  specs file `312d3e6c842efd8706270d914786a51a1175304a914e60fbcfe6215ceee45d13`;
  cache hashes are frozen in the protocol:
  SF-13 cache `174620e20f46b155a0d532b0ebb34bb6de12cecc6a1e710ced682ba4c4e9d3da`,
  SF-14 cache `a1b2c70a626e7b066cf8db911799339d1aad080048bc78e70c17e820e5d31a64`.
  Datasets and caches remain ignored local artifacts.
- Train fits only per-sensor position noise (RMS residual 3.5/4.2/4.0 m for RGB/IR/LiDAR). Validation selected six
  parameters by coordinate search over a grid fixed beforehand; the protocol freezes parameters, grid, source
  hashes and cache hashes. `score` refuses to run if any hash changed or if a test report exists.
- Selected: `accel_sigma 0.5, confirm_hits 1, gate_chi2 13.82, score_smoothing 0.8, kappa_exponent 1.0,
  noise_scale 1.0`. Validation objective 0.7223 versus static control 0.7056.
- Truth (objects, actual poses, drift) reaches only the evaluator. The tracker input is detections, availability,
  nominal poses/intrinsics, observed LiDAR points and frame time; a test perturbs truth and checks identical
  tracker output. Calibration uncertainty is a declared prior, not the simulated drift.

## Retained failed attempt

The first tuning (`attempt1-center-only-support.json`) scored validation 0.659 against static 0.706. Diagnosis on a
moving harbor clip showed that support was checked at the box *centre*: for 180 m ships the centre has no nearby
LiDAR returns and may project outside the image while the hull is visible, so the track lost all sensors and drifted
into prediction-only. Support now uses the box footprint radius (LiDAR) and centre-plus-corners (camera), covered by
two new tests. The protocol was re-tuned from scratch; the first result is kept as evidence. The test split was not
scored before the fix.

## Acceptance checklist

| Requirement | Evidence |
| --- | --- |
| Full outage: prior followed, zero correction, no covariance shrink, nothing invented | tests `full_outage_*`, `outage_state_equals_pure_prediction_bit_exactly`, `full_outage_never_births_tracks`, `zero_observation_mass_returns_prior_bit_exactly`; 0 invented observations on test |
| Loss/recovery of each sensor, brief/all outages | single-sensor loss test for each sensor; availability scenarios 1-6; 4-frame sensor and 6-frame all-sensor windows in the drift clips |
| Partial local corruption | six SF-12 corruption probes, observed mAP 0.731-0.778 versus static 0.726-0.762 |
| Calibration drift | drift/outage clip variants in every split; the tracker never reads actual drift. Drift is not estimated or corrected |
| Sequence reset, expired hypotheses | tests `reset_clears_all_state...`, `gap_beyond_the_declared_limit...`, `prediction_only_track_expires...`, `track_expires_when_position_uncertainty...` |
| Camera Jacobian / covariance fixtures | `test_temporal_geometry.py`: finite-difference checks of projection, SE(3) and composed Jacobians; pixel covariance composition |
| KNN and sample validity for zero points and off-image references | geometry tests for zero points, behind-camera, off-image; tracker tests for off-image reference and extended objects |
| Temporal/static ablation on identical splits; latency and memory | table above and `test-report.json` |
| Model-document changes | ESSRF.md decision entry, BACKLOG, [tracker profile](../TEMPORAL_TRACKER.md) |

Backend suite: 286 passed (244 before). 

## Limits

Synthetic constant-velocity targets (one moving object per layout; others static), three test layouts, a frozen
detector that never saw sequences, no learned temporal features, no learned calibration, no estimate of drift. The
tracker's calibration term is a declared tolerance. A temporal gain over the static ensemble on clean frames is
within noise; the demonstrated value is false-positive suppression, outage continuation and explicit
prediction-only labelling. Sensor-specific measurement noise includes ensemble bias because it is fitted from raw
residuals. SF-15 scaling, held-out assets and real sensors are untested.
