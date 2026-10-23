# Model card — SF-15 scaled static ensemble

## Identity

| Field | Value |
| --- | --- |
| Profile | `independent-experts-initialization-consensus.v1` (SF-Q recipe, unchanged) |
| Deployed bundle | [`scaled-model-bundle.json`](evidence/sf15-scaling/scaled-model-bundle.json), checkpoint SHA-256 `fb456975…88a1` |
| Members | Seeds 11, 12, 13 × {RGB, IR, LiDAR} × {raw-best, SWA 61–120} = 18 unimodal heads, consensus IoU 0.1 |
| Architecture | `baseline-v1` query detector (16 queries, width 64), one network per sensor; no learned fusion, ESSRF or temporal head |
| Training data | 10,000 synthetic captures, dataset SHA-256 `fedcbb5f…055b`: 2,100 SF-11, 900 SF-15 initial, 7,000 SF-15 rung |
| Recipe | 120 epochs, batch 32, constant LR 1e-3, SWA over epochs 61–120, CUDA-graph training (frozen in [protocol](evidence/sf15-scaling/protocol.json)) |
| Classes | aircraft, ground vehicle, ship (3D boxes in the rig frame) |
| Environment | Windows 11, Python 3.13.10, PyTorch 2.13.0+cu130, RTX 3090 |

## Intended use and scope

- 3D detection of the three catalog classes in this lab's procedurally generated airfield and harbor scenes.
- Inputs are the lab's own RGB 640×384, thermal IR and 32×256 LiDAR observations.
- It is the static detector for the SF-16 interactive demonstration.
- It is not validated on real sensors, real imagery or other scene families.
- Confidence is uncalibrated softmax consensus. It must not be read as a probability of correctness outside this synthetic distribution.

## Data volume decision

- The ladder was chosen on validation only.
- 3k gained +0.042 over the frozen SF-Q baseline.
- 10k gained +0.183 over SF-Q and +0.141 over 3k.
- Validation still recommended expanding. The 30k rung was not run because the user set a 10k ceiling when extending the time budget (2026-10-23), and the disk reserve would also have blocked it.
- The learning curve had therefore **not** saturated at 10k.

## Sealed-test results

Values are mean ± sample SD over three disjoint three-seed ensembles (9 seeds). The tests contain 900 frames from 18 independent layouts, and 300 more frames from 6 layouts for F-22. Full tables are in [`results-summary.json`](evidence/sf15-scaling/results-summary.json).

| Domain | Frames | SF-Q baseline mAP | Candidate mAP |
| --- | --- | --- | --- |
| Standard conditions | 600 | 0.768 ± 0.028 | 0.908 ± 0.024 |
| Held-out time/weather/severity combinations | 300 | 0.772 ± 0.010 | 0.943 ± 0.027 |
| Unseen F-22 mesh (test-only, after selection) | 300 | 0.601 ± 0.056 | 0.867 ± 0.046 |
| Whole sealed test, clean / macro over subsets and corruptions | 900 | 0.761 / 0.715 | 0.915 / 0.876 |

Per-class results on the whole sealed test (candidate, availability-7) are in the next table. Positives are per domain, and the IoU threshold is 0.25 for aircraft and vehicles and 0.5 for ships.

| Class | Positives (std / held-out / F-22) | AP standard | AP held-out | AP F-22 set |
| --- | --- | --- | --- | --- |
| Aircraft | 420 / 200 / 500 | 0.984 | 0.990 | 0.960 (F-22 only) |
| Ground vehicle | 200 / 110 / 110 | 0.743 ± 0.070 | 0.837 ± 0.080 | 0.774 ± 0.105 |
| Ship | 280 / 180 / 0 | 0.997 | 1.000 | not evaluable |

The table below covers sensor subsets and corruption probes on the sealed test. "Availability" means which sensors are present.

| Case | Baseline | Candidate | F-22 candidate |
| --- | --- | --- | --- |
| RGB only | 0.626 | 0.859 | 0.879 |
| IR only | 0.668 | 0.828 | 0.728 |
| LiDAR only | 0.711 | 0.872 | 0.743 |
| RGB+IR / RGB+LiDAR / IR+LiDAR | 0.698 / 0.728 / 0.777 | 0.885 / 0.936 / 0.885 | 0.866 / 0.890 / 0.749 |
| All sensors | 0.761 | 0.915 | 0.867 |
| No sensors | 0 detections | 0 detections | 0 detections |
| RGB known / OOD corruption | 0.758 / 0.746 | 0.865 / 0.868 | 0.742 / 0.743 |
| IR known / OOD corruption | 0.713 / 0.670 | 0.914 / 0.876 | 0.852 / 0.874 |
| LiDAR known / OOD corruption | 0.736 / 0.756 | 0.883 / 0.835 | 0.865 / 0.854 |

Per-condition results:
- Each of the 10 standard and 10 held-out environment presets has 60 or 30 frames and identical class counts.
- Standard presets range from 0.880 (night 21:00) to 0.932.
- Held-out presets range from 0.897 (dense fog 19:00) to 0.980.
- F-22 is weakest at night: 0.751 and 0.786.

Calibration and localization on the whole sealed test, for the candidate:
- Detection ECE (10 bins) is 0.063 on standard and 0.063 on held-out scenes.
- Matched centre error is 3.1 m on standard and 3.4 m on held-out scenes.

## Frozen SF-11 targets

Every target was checked for each of the three ensembles; see `sf11_targets` in the summary.

| Target | Result |
| --- | --- |
| Class AP ≥ 0.50 / 0.50 / 0.762 (ship) | Pass |
| Recall ≥ 0.70 per class | Pass |
| Per-condition mAP floors | Pass |
| Centre error ≤ 5 m | Pass |
| ECE ≤ 0.15 | Pass |
| p95 latency ≤ 500 ms | Pass (93 ms) |
| Training peak allocation ≤ 18 GiB | Pass (2.6 GiB) |
| **Empty-scene false positives ≤ 0.10 per empty frame** | **Fail: 0.544–0.644** (SF-Q baseline 1.289). The F-22 set has only 10 empty frames, with 0 false positives. |

The empty-scene failure was already visible on validation (0.49–0.68 per empty frame). It was not detected before test because the volume rule only checks clean and macro mAP. The ensemble emits low-confidence boxes in object-free frames; there is no score cutoff or abstention head. Fixing it needs a model revision, such as a validation-selected confidence cutoff or a no-object calibration, followed by fresh test data, because this sealed test is spent.

## Runtime

End-to-end inference per capture includes loading observations, 18 heads and consensus. It was measured over 200 repetitions on the RTX 3090.

| Bundle | p50 | p95 | Peak allocated / reserved | Process peak RSS |
| --- | --- | --- | --- | --- |
| Candidate | 79.7 ms | 93.4 ms | 19 MB / 31 MB | 1.20 GB |
| SF-Q baseline | 78.7 ms | 90.3 ms | 19 MB / 31 MB | 1.20 GB |

## Temporal ablation (post-selection, descriptive)

- The SF-14 tracker was applied with its frozen parameters to the candidate's predictions on the historical SF-13/SF-14 test clips: 192 frames in 6 sequences.
- On clean data, static mAP is 0.779. The SF-14 report gave 0.740 for the SF-Q ensemble on the same clips.
- With the tracker, observed-detection mAP is 0.788. Including prediction-only output, it is 0.862.
- Across subsets and corruptions, the tracker changes observed-detection mAP by −0.04 to +0.04.
- As in SF-14, the tracker's demonstrated value is continuation through outages, which is labelled prediction-only. It does not establish a quality gain, and this is not a fresh temporal holdout. See [`temporal-ablation.json`](evidence/sf15-scaling/temporal-ablation.json).

## Limitations

- All data is synthetic, from one procedural generator, with three classes and two site families. There is no sim-to-real evidence.
- Training mixes renderers: SF-11 captures are SwiftShader (CPU ANGLE) and SF-15 captures are NVIDIA ANGLE. Renderer effects were not ablated.
- The held-out asset result covers one aircraft mesh (F-22), not arbitrary unseen assets. The F-22 set contains no ships. F-22 IR-only and LiDAR-only results (0.73/0.74) are much weaker than RGB-only (0.88).
- Ground vehicles are the weakest and least stable class (AP 0.74 ± 0.07 on standard scenes).
- Empty-scene false positives miss the frozen target (see above).
- Sealed-test protocol deviation: the first scoring run crashed after printing 48 clean-case lines. After the evaluator fix, one approved re-run reproduced those lines exactly; see [graph-crash record](evidence/sf15-scaling/graph-crash/README.md). Selection never used test data.
- Corruption probes are fixed synthetic perturbations, not real sensor-fault families.
- Ensemble SD measures variation between disjoint three-seed ensembles; it is not a dataset-sampling confidence interval.
