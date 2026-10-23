# Static dataset scaling and storage (SF-15)

The frozen [protocol](evidence/sf15-scaling/protocol.json) keeps the SF-Q static
recipe and evaluator. It compares three disjoint complete ensembles, each with
three initializations and raw/averaged snapshots per sensor (18 networks).
All nine training seeds count. More captures alone do not pass acceptance.

## Data selection

The first rung has 3,000 train captures: the existing 2,100 SF-11 train captures
plus 900 new captures. New independent scenes supply 600 validation captures,
600 standard test captures and 300 test captures with new time/severity/weather
combinations. The latter test domain is reported separately. A later catalog audit
before validation found F-22 absent from historical/new training (14/15 asset IDs
exposed), so 300 additional test-only captures on six fresh airfield layouts are
reserved for that unseen mesh. Their report is separate and cannot select a model.
This remains one unseen aircraft mesh; it does not establish arbitrary unseen-mesh
or real-sensor robustness.

`generate-sf10-requests.ts --split-layouts TRAIN,VALIDATION,TEST` assigns entire
50-capture layout families explicitly; the counts must sum to `--layouts`.
The historical default generator output remains unchanged. Explicit splits allow
up to 1,000 layouts. `--condition-profile sf15-heldout` changes only environment
parameters, never geometry or camera poses; it is used solely for test scenes.

`app.scaling.compose` preserves source split labels, capture order and manifest
hashes. It checks group, sequence and physical world identities across splits,
ignoring a cosmetic world ID. Immutable capture files are linked into the selected
dataset, avoiding a second physical copy. NTFS link exhaustion falls back to a
byte copy; no source file is rewritten. Independent captures are copied/validated
in a process pool before final manifest validation.

No test supervision is read by the new training/cache preparation path. Validation
selects raw snapshots, data volume and the final contender. Before test access,
the runner freezes source, protocol, data and every candidate/control checkpoint.
Hash changes or an existing test report prevent another scoring run.

## Running and resuming

Use the pinned learning dependencies from `backend/learning-env/pyproject.toml`.
The measured installation is the system Python 3.13.10 with PyTorch 2.13.0+cu130;
the empty `.venv-learning` directory is not that installation.

```powershell
python tools/profile-workload.py --output artifacts/sf15/RUN-PROFILE -- python tools/run-scale-experiment.py --hours 11
```

The user authorized at most 12 hours; one hour is reserved for preflight and eleven
for the resumable experiment. Re-run the same runner command (using a fresh profile
directory) to resume. `experiment-state.json` retains the original start/deadline,
commands, exit codes and log paths. A plain resume never extends the deadline.
Only `--extend-hours H --extension-authorization "<user's words>"` appends a
`budget_extensions` window that starts at grant time; `started_epoch_s` and
`hours` stay frozen and the same authorization cannot be recorded twice. Never
resume an expired budget without one: the ladder would stop and run the one-shot
sealed test on the smaller rung.

On 2026-10-23 the user granted +4 h with a 10k ceiling after the original
window expired during `capture-10000` (1,533/7,000 captured; about 1.5 h of the
11 h had actually been used). The resume command was:

```powershell
python tools/profile-workload.py --output artifacts/sf15/RUN-PROFILE-resume2 -- python tools/run-scale-experiment.py --hours 11 --max-train 10000 --extend-hours 4 --extension-authorization "2026-10-23 user: +4 h, ceiling 10k"
```
A failed training checkpoint is not silently treated as completed. Keep 20 GiB
free and reserve evaluation time before starting the next capture rung.

`--max-train 3000` or `10000` can impose a smaller upper rung before starting.
The generator uses six measured persistent capture sessions on this host. This
is a host-specific measurement, not a general optimum. Capture is CPU-bound
(GPU ANGLE rendering, 13-17% GPU utilization); three sessions give about 79% of
six-session throughput with byte-identical outputs (`parity-w3/w6.json`).
Every stage runs at Windows `below-normal` priority by default (`--priority`).
Chromium resets its renderers (about 85% of capture CPU) to normal and its GPU
process to above-normal, so inheritance alone is insufficient; the runner
re-lowers the stage process tree every 2 s. Interactive applications then take
the CPU first. Task
Manager still reports near-100% CPU while the machine is otherwise idle. Clean expert predictions
are reused across sensor-subset scoring because these independent unimodal
networks never read other sensors; observation-level corruptions are reprocessed.

## Storage policy

Directory size counts each hardlink name. It does not measure allocated disk
space: worker outputs and published datasets already share many file records.
On 2026-10-23 Explorer showed 25 GB for `artifacts/sf11` and 142 GB for all
artifacts; the physical totals were about 3.5 GB and 60.5 GB. A new capture
costs about 8 MB physically, so the 10k rung needs about 45 GB and a 30k rung
would not pass the 20 GiB disk reserve on the current volume.
Keep original source manifests, checkpoints and negative-result reports.

`tools/storage-maintenance.py --dataset DATASET --worker-root WORKERS
--deduplicate --apply --report REPORT.json` removes worker raw files only after
verifying matching IDs, sizes and SHA-256 in the surviving published dataset.
It retains request/result/metadata provenance and refuses continued-thermal worker
pruning. It also replaces byte-identical large manifest-owned arrays with hardlinks,
using groups of at most 128 links to leave NTFS headroom. Only sealed immutable
data may be maintained this way. Retired worker mirrors must not be reused as
complete raw jobs; use the published dataset or a fresh worker root.

Old SF-12 preprocessing caches are reproducible from the retained SF-11 data.
Their exact removed hashes and regeneration commands are recorded in
[`derived-cache-prune.json`](evidence/sf15-scaling/derived-cache-prune.json).
The rest of `artifacts/sf12`, including its checkpoints, was deleted on
2026-10-23 because backward reproducibility is no longer required. Volume free-space
changes include concurrent writes; do not add logical removed bytes to physical
space savings.

The old replay dataset directories under `artifacts/perf-speed` and
`artifacts/perf-sf10` have been retired after comparing every data file with
`artifacts/sf10/pilot-300-v4`; the remaining roots were deleted on 2026-10-23. Exact
per-capture runtime metadata is under `artifacts/retired-replay-metadata`.
Historical commands naming those old replay data directories must use the
canonical data instead. See [retirement inventory](evidence/sf15-scaling/replay-retirement.json).

| Historical data | Decision |
| --- | --- |
| SF-11 `pilot-3000` | Retain unchanged manifest/data; reuse only its 2,100 train captures |
| SF-11 raw worker mirrors | Deleted 2026-10-23 (data survives in `pilot-3000`) |
| SF-Q weights, fresh holdout and reports | Retain for matched control and historical acceptance |
| SF-13/SF-14 datasets and replay state | Retain for temporal regression and post-selection ablation |
| SF-10 performance replay copies | Deleted; canonical SF-10 and runtime metadata remain |
| Benchmarks, profiler dumps, SF-12 caches/checkpoints, superseded SF-Q runs, `capture-jobs`, `perf-*` | Deleted 2026-10-23 at user request (3.55 GiB physical, 8.6 GiB logical); keep SF-Q `baseline-120*`, `swa-seed-*`, `cases`, `fresh-holdout`, `acceptance*` and `sf11/cuda` |
| Small clean-checkout/browser fixtures | Retain reproducibility evidence; they are not the main storage cost |
