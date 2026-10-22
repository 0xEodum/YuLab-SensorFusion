# Static dataset scaling and storage (SF-15)

The frozen [protocol](evidence/sf15-scaling/protocol.json) keeps the SF-Q static
recipe and evaluator. It compares three disjoint complete ensembles, each with
three initializations and raw/averaged snapshots per sensor (18 networks).
All nine training seeds count. More captures alone do not pass acceptance.

## Data selection

The first rung has 3,000 train captures: the existing 2,100 SF-11 train captures
plus 900 new captures. New independent scenes supply 600 validation captures,
600 standard test captures and 300 test captures with new time/severity/weather
combinations. The latter test domain is reported separately. The existing asset
catalog was already exposed in historical training, so this does not establish
generalization to unseen object meshes or real sensor faults.

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
commands, exit codes and log paths. It never extends the deadline on resume.
A failed training checkpoint is not silently treated as completed. Keep 20 GiB
free and reserve evaluation time before starting the next capture rung.

`--max-train 3000` or `10000` can impose a smaller upper rung before starting.
The generator uses six measured persistent capture sessions on this host. This
is a host-specific measurement, not a general optimum. Clean expert predictions
are reused across sensor-subset scoring because these independent unimodal
networks never read other sensors; observation-level corruptions are reprocessed.

## Storage policy

Directory size counts each hardlink name. It does not measure allocated disk
space: worker outputs and published datasets already share many file records.
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
Weights, supervision and negative-result reports survive. Volume free-space
changes include concurrent writes; do not add logical removed bytes to physical
space savings.
