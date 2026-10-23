# SF-15 sealed-test crash and evaluation fix (2026-10-23)

## What happened

The resumed runner (`4d9225e`, then the stage-priority fix `50b089b`) finished
`capture-10000`, `compose/prepare-10000`, all 27 trainings and `validation-10000`.
The 10k decision promoted the candidate, with an objective gain of +0.183 vs the
SF-Q baseline and +0.141 vs 3k. `selection.json` and `freeze.json` were written.
`freeze.json` has SHA-256 `15703c4903c04a4036c6719626b7f77318a09e6c39fbddbc183df157c96a87ce`.

`sealed-test` then failed with `CUDA error: an illegal memory access` inside
`GraphInference.infer` on the first corrupted case (`rgb-known`). No
`test-report.json` was written. **Disclosure:** before the crash, the clean
case had already been scored, and 48 clean test-metric lines
(`test <method> <group> <case> <mAP>`) are in `artifacts/sf15/logs/sealed-test.log`.
The model selection was frozen before any test access. Nothing was selected
or tuned using these lines.

## Diagnosis (label-free; no test supervision read or scored)

`inference-only-repro.py` loads cached test features only. `sequence-repro.py`
replays the evaluate order with the same features and checkpoints.

| Sequence | Result |
| --- | --- |
| All 108 models, graphs captured directly on `rgb-known` | OK |
| Clean graphs, then `rgb-known` replay, without the reload phase | OK |
| Clean graphs, reload-parity phase (108 temporary graphs captured and deleted), then `rgb-known` replay | Illegal access on the first model (`baseline 11 rgb raw`) |
| The same, plus recapturing the main models' graphs after the reload phase | OK |

Capturing and deleting the temporary reload graphs invalidates graphs that
were captured earlier and are still in use. This is consistent with CUDA-graph
capture clearing or reusing the cuBLAS workspace and graph memory pools. The
exact allocator mechanism was not isolated. Validation ran the same order without crashing.

## Fix and validation recheck

`tools/scale-ensemble.py` now recreates `GraphInference` for every main model
right after the reload loop.

The fixed evaluator was re-run on validation for both rungs:
`validation-10000-recheck.json` and `validation-3000-recheck.json`. All 27,184
compared values per report were identical to the originals (`elapsed_s`
excluded). Every per-method prediction file has the same SHA-256. The
corrupted-case validation numbers were therefore not silently corrupted, and the
10k selection stands.

## Consequence for the sealed test

`freeze.json` hashes `tools/scale-ensemble.py`, so the fix intentionally makes
it refuse another run. Re-scoring requires a new freeze over the fixed source.
That freeze must keep the same checkpoints, manifests and protocol, and needs
explicit user approval as a deviation from the one-shot test protocol. Parity
gate: the new run's 48 clean lines must equal the crashed run's lines exactly.
