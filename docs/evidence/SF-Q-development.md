# SF-Q quality investigation: implementation checkpoint

2026-10-09. The user authorizes alternate fusion paradigms, data changes, and
immediate training. This checkpoint implements exploration, independent-expert
consensus, observation-only live inference, and immutable holdout acceptance.
The goal remains open until paired holdout and three-seed acceptance complete.

The first failing test command was
`PYTHONPATH=backend python -m pytest backend/tests/test_robust_query.py -q`:
exit 1, missing `learning.robust_query`. The implemented loss passes equal
fractional-error, small-object sensitivity, empty-target gradient, pi-periodic
yaw, unavailable-sensor isolation, and native/reference gradient contracts.
Consensus tests verify class isolation, pi-equivalent yaw, availability scoring,
and all-missing abstention. Gate tests reject changed checkpoint/protocol/data/
source and use sample SD with the strongest control. Live inference fixtures
reproduce detections after annotation and truth files are replaced with poison.

Local verification before holdout: 211 backend tests passed before the additional
live inference fixture; that fixture and five consensus/gate tests then passed.
`npm run verify` exited 0, including contract generation, typechecks, world,
sensor, asset, backend and frontend build gates. Full final verification is
recorded with acceptance evidence. No visual behavior changed in this milestone.

The current RTX 3090 is shared with an unrelated Python training process. It is
preserved. Short profiling checks loss/gradient and exact prediction/metric parity
before measuring complete epochs. Features are already GPU-resident (638,112,000
bytes); graph replay and native assignment remain appropriate. Startup is
reported separately. Per-process timings are useful; aggregate NVIDIA utilization
cannot be attributed solely to this task under concurrent training.

Negative experiments are retained under `artifacts/sf-quality/`: balanced clean
fusion .526/.236 clean/macro; augmented fusion .435/.370; wider augmented fusion
.471/.425. They are not promoted. Unweighted independent experts at 120 epochs
per expert produce validation .629 +/- .006 clean and .557 +/- .015 macro across
seeds 11/12/13. The rule and all budgets were frozen before confirmatory seed
training in `sf-quality/selection-protocol.json`.

The candidate comprises three independently trained networks. Controls include
every unimodal network, 120-epoch feature fusion, and 360-epoch feature fusion.
Training/inference cost and the finite synthetic corruption family are explicit.
The first 120 epochs of the new constant-rate 360-epoch fusion harness match the
original seed-11 loss and clean validation mAP exactly. No test observations were
read during development; final selection cannot be changed against that holdout.
