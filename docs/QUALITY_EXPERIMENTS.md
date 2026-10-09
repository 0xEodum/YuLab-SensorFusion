# Static sensor-fusion quality recovery

2026-10-09. User-authorized architecture and data changes supersede the previous
requirement to finish temporal ESSRF before improving the static detector. ESSRF
is optional. SF-Q is the current work item; temporal capture remains planned.

Acceptance uses the existing upright oriented 3D AP evaluator: aircraft and
ground vehicles at IoU .25, ships at .5. Minimum targets are clean mAP > .45,
degradation macro > .30, and sample standard deviations < .03 for both metrics
over at least three seeds. Stretch targets are > .50 and > .35. The candidate
must beat equal-budget fusion and the strongest unimodal control. Validation is
for exploration; freeze configuration and checkpoint-selection rules before
confirmatory seeds and holdout evaluation. Failed holdout acceptance cannot be
repaired by tuning against that same holdout.

The degradation macro is unchanged from SF-12: availability masks 1 through 6
and the six raw-observation corruption probes. Clean is availability-7.
Availability-0 is an abstention check, excluded from the macro. Corruption probes
are synthetic and include previously exposed families; they do not establish
real-world or unseen-corruption robustness. All methods use identical examples,
unchanged labels, sensor calibration, and evaluator thresholds.

The first alternative keeps the compact global query backbone and replaces the
fixed 200 m localization penalty with object-size-normalized localization,
including a .5 m scale floor and pi-periodic upright-box yaw loss. Explicit
availability masks prevent unavailable streams influencing predictions; null
input produces exactly zero detections. Optional training augmentation samples
nonempty sensor subsets and contaminates image feature regions. Evaluation
continues to corrupt raw sensor observations before fixed preprocessing.

Small CUDA runs establish cost before larger budgets. Native assignment and
graph replay remain available. The original baseline default and SF-12 evidence
are preserved. New runs live under ignored `artifacts/sf-quality/`; source,
protocol, and summarized evidence belong in version control. The initial
exploration uses seed 11, then freezes a candidate before seeds 12 and 13.

Example commands (repository root, learning environment):

```powershell
python tools/quality-pilot.py profile --output artifacts/sf-quality/profile-eager --execution eager
python tools/quality-pilot.py profile --output artifacts/sf-quality/profile-graph --execution graph
python tools/quality-pilot.py train --output artifacts/sf-quality/candidate --epochs 200 --width 128 --augment --full-probability .75
python tools/quality-pilot.py evaluate --output artifacts/sf-quality/candidate --width 128
```

These commands read train/validation only. Holdout access uses a frozen
configuration and checkpoint-hash gate. Checkpoints
include source revision, preprocessing, seed, budget, and dataset hash.

The selected paradigm is now independent experts with detection consensus, using
the [frozen protocol](evidence/sf-quality/selection-protocol.json). Exploratory
seed-11 clean/macro results: extended simple fusion .397 (clean); balanced clean
query fusion .526/.236; balanced augmented fusion .435/.370; width-128 augmented
fusion .471/.425; independent-expert consensus .625/.540. The first consensus
rule was frozen without a weight or overlap-threshold search. These are
validation findings, not holdout acceptance. The three-seed validation consensus
is .629 +/- .006 clean and .557 +/- .015 macro before the holdout check.

`tools/quality-holdout.py` now freezes every checkpoint and inference-source hash,
prepares raw-observation corruption cases only after that gate, and evaluates
candidate and controls on identical validation/test frames. `freeze`, `prepare`,
and `evaluate` are separate commands. Any changed checkpoint, source, dataset,
or protocol invalidates the gate. The 360-epoch fusion control measures whether
the advantage survives a larger single-model training budget; expert consensus
has three networks and its inference/training cost is reported explicitly.

Persistent observation-only inference is available through
`tools/infer-decision-fusion.py`, producing the canonical `PredictionBundle`.
Pass three expert checkpoints in RGB, IR, LiDAR order. It validates matching seed,
dataset and preprocessing, skips unavailable experts, and identifies the complete
ensemble with a composite checkpoint hash. Model load time is separate from
observation read/preprocessing, inference, and consensus latency.
