# SF-14 temporal tracker: `ensemble-kalman-tracker.v1`

SF-14 does not train `essrf-temporal-v1`. The accepted SF-Q ensemble (18 frozen networks) stays the
per-frame detector; a small observation-only tracker consumes its **per-sensor** consensus detections.
The decision, its evidence and the reasons for replacing the proposal are recorded in
[ESSRF.md](ESSRF.md) section 0 and the [SF-14 acceptance report](evidence/SF-14-temporal.md).

## Why this architecture

- Learning temporal state needs sequences. The SF-13 pilot has 64 training frames; static ESSRF already failed
  to train on 2,100 captures (SF-12). A learned temporal head would be fitted to a handful of clips.
- The static ensemble is the strongest measured detector. Keeping it frozen makes the temporal comparison
  matched and attributable: any difference comes from state propagation and gating, not retraining.
- ESSRF's structural requirements are kept as tests: zero observation mass returns the prior exactly,
  full outages invent nothing, calibration uncertainty widens sampling support, and sensors are handled
  per query rather than by one global score.

## State and update

World-axis tracks (east-up-south) hold a constant-velocity ground-plane state `s = (x, z, vx, vz)` with
covariance `P`, plus random-walk attributes `(y, w, h, l, yaw)` and class mass. Prediction uses white-noise
acceleration `Q(dt)`. Measurements are updated in information form with observation mass `kappa in [0, 1]`:

```
P+ = (P-^-1 + kappa H^T R^-1 H)^-1        s+ = s- + P+ kappa H^T R^-1 (z - H s-)
```

`kappa` is the detection score raised to `kappa_exponent`. `kappa = 0` takes a separate path and returns
the prior arrays unchanged, so a measurement can neither move a track nor shrink its covariance. If no
sensor is available, no measurement code runs at all: tracks follow the prior, `P` grows, nothing is born
and detections still present in a malformed bundle are ignored.

## Gating and support

For every track and sensor the predicted reference must be *supportable* before it can be updated:

- **Camera (RGB, IR):** the reference is projected with the nominal pose and ideal-pinhole intrinsics. The pixel
  covariance is `J_x P J_x^T + J_xi Sigma_cal J_xi^T + sigma_pix^2 I` (analytic projection and SE(3) Jacobians,
  checked against finite differences). The reference is observable if it is in front of the camera and the
  3-sigma bounding box of that ellipse reaches the image. Off-image or behind-camera references receive no
  camera update and are never penalised as misses for that sensor.
- **LiDAR:** observed points within `lidar_radius_m + 3 sigma` of the reference must exist (k-nearest offsets);
  an empty or distant neighbourhood is invalid and finite, never imagined.
- **Measurement noise:** `R = sigma_sensor^2 I + J_cal Sigma_cal J_cal^T` projected to the ground plane, so
  extrinsic uncertainty widens both the association gate and reduces the gain, growing with range.
  `Sigma_cal` is a *declared nominal tolerance* (rotation 0.01 rad, translation 0.2 m). It is not read from the
  simulated drift, which is truth and never enters model input.
- Association is per sensor (LiDAR, IR, RGB order), Hungarian on Mahalanobis distance with a chi-square gate
  and class agreement. A detection explained by a track the sensor cannot support is ignored, not born.

## Lifecycle

Tentative tracks need `confirm_hits` matches inside `confirm_window` frames to be emitted. Confirmed tracks that
are not matched continue as **prediction-only** (`observed = False`) with a decaying score until they miss
`max_missed_frames` frames or their position sigma exceeds `max_position_sigma_m`. A strictly increasing frame
time is required; a gap above `max_gap_s` expires every track (`last_reset_reason = "time-gap"`) and `reset()`
restarts identities for a new sequence.

## Measured parameters

Position noise per sensor is fitted from train-split residuals; remaining parameters come from a fixed
coordinate-search grid scored only on validation clips (see the protocol in the evidence directory). Test
clips are scored once after sources, caches and protocol are frozen.

## Scope

Synthetic constant-velocity targets, global-shutter cameras and the SF-13 outage patterns. Prediction-only
boxes keep the last estimated extents and are not an observed detection. No learned temporal feature or
learned calibration is claimed. Pitch/roll, acceleration and rolling shutter are outside the motion model.
