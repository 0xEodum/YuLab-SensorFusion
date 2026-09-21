# Sensor-fusion lab implementation backlog

Updated: 2026-09-21. SF-02R procedural landscape quality passed local acceptance.
SF-03 streaming and navigation is READY. Dataset generation and training remain
later stages.

Read [ARCHITECTURE.md](ARCHITECTURE.md), [DATA_CONTRACTS.md](DATA_CONTRACTS.md), and
the implementation profile in [ESSRF.md](ESSRF.md) before changing code.

## Execution rules

- `READY` is the next executable item; keep only one READY or IN PROGRESS item.
  `PLANNED` is dependency-blocked, `DONE` requires its acceptance evidence.
- Work in order below. Split a task if it cannot be reviewed as a coherent
  change; preserve its acceptance requirements in named child tasks.
- Write meaningful deterministic tests for new world/sensor/model contracts.
  Preserve legacy terrain behavior during the initial repository move.
- Verification is local only, including browser acceptance. Do not add or run
  hosted GitHub workflows; this supersedes the original SF-01 CI requirement.
- Commit and push each coherent, verified checkpoint. Do not accumulate several
  completed milestones in one unpushed change. Use explicit staging; exclude
  datasets, secrets, external source trees and large checkpoints from normal Git.
- Each completed task records source revision, commands/exit codes, fixture and
  artifact hashes, environment, results and known limits under `docs/evidence/`.
  A later evidence commit may reference the tested implementation commit to avoid
  impossible self-referential hashes. Confirm push success and clean status.
- Real browser checks are required for visual changes. Test/build success alone
  does not establish sensor correctness, model convergence or physical realism.
- Update model/contract documentation in the same checkpoint as behavior changes.
  Failed acceptance stays open; a reduced scope is explicitly renamed/documented.

## Roadmap and user-request coverage

| Item | Outcome | Depends on | Status |
| --- | --- | --- | --- |
| SF-00 | Architecture, data semantics, implementation plan | Baseline inspection | DONE (planning only) |
| SF-01 | Frontend/backend split, schema and verification foundation | SF-00 | DONE |
| SF-02 | Connected deterministic world-space terrain foundation | SF-01 | DONE (foundation only; quality correction below) |
| SF-02R | Procedural landscape richness and legacy visual quality | SF-02 | DONE |
| SF-03 | Chunk streaming, navigation and sensor residency | SF-02R | READY |
| SF-04 | Asset import and first aerodrome | SF-03 | PLANNED |
| SF-05 | Shared capture worker and synchronized RGB/reference passes | SF-04 | PLANNED |
| SF-06 | Surface heat and thermal IR | SF-05 | PLANNED |
| SF-07 | Occlusion-correct LiDAR | SF-06 | PLANNED |
| SF-08 | Weather, time and sensor noise | SF-07 | PLANNED |
| SF-09 | Remaining asset catalog and coast/harbor world | SF-08 | PLANNED |
| SF-10 | Visibility labels and immutable dataset generation | SF-09 | PLANNED |
| SF-11 | Pilot dataset and unimodal/simple-fusion baselines | SF-10 | PLANNED |
| SF-12 | Compact ESSRF and subset/reliability validation | SF-11 | PLANNED |
| SF-13 | Temporal capture and uncertain calibration | SF-12 | PLANNED |
| SF-14 | Temporal/calibration-aware ESSRF | SF-13 | PLANNED |
| SF-15 | Scale dataset, train and evaluate final candidate | SF-14 | PLANNED |
| SF-16 | Interactive trained-model demonstration | SF-15 | PLANNED |
| SF-17 | Reproducible delivery and full regression | SF-16 | PLANNED |

| User request | Delivering tasks |
| --- | --- |
| 1. Expand maps | SF-02, SF-02R, SF-03, SF-09 |
| 2. RGB + IR + viewpoint-limited LiDAR | SF-05 through SF-08 |
| 3. Generated models, heat, aerodrome | SF-04, SF-06, SF-09 |
| 4. Weather/time/noisy varied data | SF-08, SF-10, SF-13 |
| 5. Frontend/backend separation | SF-01 |
| 6. Visible labels, tri-modal detector and training | SF-10 through SF-15 |
| 7. Interactive model/weather demonstration | SF-16, SF-17 |
| Keep ESSRF text aligned | SF-12, SF-14, SF-15 and every model change |
| Commit and push as work progresses | Every verified checkpoint |

The compact profile is a diagnostic milestone, not a replacement for the full
temporal profile. Replacing or reducing the final architecture requires an
explicit evidence-backed revision to ESSRF and this backlog.

## SF-00 — Plan and baseline

Evidence: inspected original source revision
`f8879c1bdb7446d682f9a6c7a58f4f08a012806b`, the sole existing design document, and
external model catalog. Existing `npm run build` and `npx tsc --noEmit` passed.
Recorded environment and limitations in ARCHITECTURE. No browser or sensor
acceptance is claimed for this documentation-only milestone.
See [planning evidence](evidence/SF-00-planning.md) for checks and scope limits.

## SF-01 — Repository and contract foundation

Deliver: npm workspace frontend move, isolated Python backend, loopback health/
capability endpoint, canonical JSON Schemas/OpenAPI and generated bindings for
the payload families in DATA_CONTRACTS, local launch instructions and checks.

Acceptance:

- Original presets, seed controls, orbit and PNG/OBJ/GLB exports remain usable;
  build, explicit typecheck and browser smoke pass from a clean checkout.
- Schema positive/negative fixtures cover units/frames, unavailable sensors,
  errors, finite values, ranges, IDs and version rejection; both runtimes validate
  the same fixtures and regenerated bindings produce no diff.
- Backend health is callable through the frontend development proxy; unavailable
  backend is an explicit UI state. No fake sensor/training capabilities advertised.
- Locked dependencies, documented versions and local verification run without the external
  `K:` model source path. Dataset/checkpoint/cache ignore policies are in place.

Suggested checkpoints: structural move and browser baseline; contract/backend
foundation with cross-runtime validation. Run acceptance after each checkpoint.

Closed by user instruction on 2026-09-21. See [SF-01 evidence](evidence/SF-01-foundation.md)
and its verification manifest; hosted-run failures remain documented. Future
acceptance uses local checks only.

## SF-02 — Connected world generator

Deliver: extracted deterministic field/meshing package, continuous base terrain,
world-space biome/feature definitions, chunk addressing and stable placement IDs.
Preserve arches, tunnels and overhangs as actual geometry.

Acceptance:

- 2,048 x 2,048 m target extent is represented by connected 128 m chunks; no
  repeating isolated diorama bases, arbitrary stretching or terrain holes.
- Same configuration produces identical geometry/placement hashes under different
  chunk request orders, including negative coordinates and seed zero.
- Neighbor boundary samples/vertices agree within declared mesh tolerance;
  normals/lighting and material transitions pass browser edge inspection.
- Geometry tests retain a through-arch/tunnel, overhang and occluded cavity;
  legacy preset characterization changes are intentional and recorded.

Completed in `b314e99` with local core, full-world and production-browser checks.
See [SF-02 evidence](evidence/SF-02-connected-world.md) and
[verification manifest](evidence/sf02-verification-manifest.json). Both full
256-chunk seed sweeps pass; legacy geometry/color hashes remain unchanged.
The preview deliberately loads four fixed chunks. Streaming remains SF-03.

User review on 2026-09-21 rejected the connected preview's visual simplification:
nearly flat ground and coarse primary forms are substantially poorer than the
original scenes. The recorded connectivity/geometry tests remain valid, but do
not establish full procedural landscape quality. SF-02 closure is therefore
limited to its technical foundation; SF-02R is required before SF-03 proceeds.

## SF-02R — Restore procedural landscape quality

Deliver: a connected procedural landscape with terrain and formation detail
comparable to the original editor, retaining SF-02's world-space contracts.
This is a required correction, not optional polish deferred to asset imports.

Acceptance:

- Replace the nearly flat presentation with visible, coherent terrain relief at
  regional and local scales: hills/ridges, valleys and irregular rock/ground
  transitions. The ground between landmarks must also carry procedural detail.
- Generate feature distribution and formation variation from the world seed.
  Four fixed showcase primitives are insufficient as the generated map. Seed
  changes must visibly affect layout and formations, not only colors or rocks.
- Adapt the original presets' density detail and low-poly visual character to
  world space: irregular arches, cliffs, overhangs, cavities and appropriate
  surface detail/decorations. Increasing triangle count alone is insufficient.
  Retain actual volumetric openings and the existing legacy editor behavior.
- Record side-by-side browser views against the original Canyon, Alpine,
  Islands and Coast scenes at comparable framing and scale. Include close-up
  and multi-chunk overview views for at least three fixed seeds, including zero.
  Explicitly assess formation shape, ground relief, surface detail and material
  transitions; do not infer visual parity from topology tests or face counts.
- Rerun deterministic order/placement, negative-coordinate, seam/normal/color,
  full-domain coverage/topology, opening/occlusion and browser regressions on
  the final profile. Version changed field/geometry semantics and preserve
  prior evidence instead of silently replacing its hashes.
- Record generation cost and preview mesh counts, keeping quality/resource
  tradeoffs explicit. All verification remains local. Streaming, mixed-pitch
  LOD and navigation stay in SF-03 after this quality correction.

Completed in implementation checkpoint `c21a562` after the RED/GREEN commits
recorded in [SF-02R evidence](evidence/SF-02R-procedural-quality.md). The v2
profile generates 16 seeded regions with multi-scale terrain, volumetric
openings, trees and rocks; the browser renders a nine-chunk overview and
landmark-detail view. Legacy/current comparisons cover all four families and
three connected-world seeds. Two complete 256-chunk sweeps, repository-wide
checks, coverage, and development plus production-built Edge suites passed
locally. Prior v1 reports and hashes remain unchanged.

## SF-03 — Streaming and navigation

Deliver: bounded chunk cache, worker generation, cancellation, free navigation,
rig pose bookmarks, display LOD and independent sensor-geometry residency.

Acceptance:

- A repeatable traversal crosses at least 100 chunk boundaries without cracks,
  stale chunks, incorrect instance IDs, or monotonic resource growth after warmup.
- Resident geometry obeys configured limits; disposed resources are verified.
- Sensor capture blocks until all possible in-range occluders are ready. Tests
  cover an occluder outside the display frustum and just across a chunk boundary.
- Meet or explicitly revise ARCHITECTURE's interactive frame-time targets with
  a recorded hardware/scene profile; report p50/p95, memory and generation latency.

## SF-04 — Import pipeline and first aerodrome

Deliver: repeatable source-to-GLB/metadata adapters, F-16 and RQ-4 aircraft plus
one ground vehicle, catalog UI, seeded placement and procedural aerodrome.

Acceptance:

- Imported meshes retain recognizable source geometry/materials and source hashes;
  dimensions, axes, normals, named heat regions and contact points are verified.
- All runtime resources are self-contained; a clean checkout plus catalog bundle
  works without source projects. Missing assets fail by name and reason.
- Runway/apron/taxiway/hangars/tower/road appear on graded connected terrain.
  Aircraft contact and placement checks exclude unintended intersections.
- Capture fixtures include an unobstructed aircraft, partial hangar occlusion and
  fully hidden aircraft. No source application behaviors/projectiles are imported.

## SF-05 — Capture worker and RGB/reference passes

Deliver: backend-owned capture jobs, Node/headless Chromium worker, shared browser
sensor package, rig calibration, RGB plus depth/instance reference passes and
synchronized preview panes. Establish renderer/device capability handshake.

Acceptance:

- A saved rig produces the same view offline and interactively at a frozen tick;
  resize/orbit/UI overlays do not change capture dimensions, pose or labels.
- Known projection fixtures agree within 0.5 pixel away from raster boundaries;
  ID round trips are exact and depth/raster orientation is verified.
- Helpers, grids and decorative shadow floor are absent from sensor geometry.
  Separate sensor extrinsics produce appropriate parallax/occlusion.
- Worker crash, timeout, context loss and cancellation yield explicit failed or
  cancelled jobs, never completed partial frames. Browser closure does not stop
  accepted jobs. Measure throughput and GPU/CPU memory before choosing queue size.

## SF-06 — Heat and IR

Deliver: versioned thermal surface metadata, off/idle/running heat states,
fixed-step thermal evolution and LWIR radiance/noise pipeline with raw export.

Acceptance:

- Analytical/simple-node fixtures validate equilibrium and cooling direction,
  timestep stability, emissivity and monotonic temperature/radiance response.
- IR remains available with RGB illumination disabled. Equalized background/object
  temperature reduces contrast under controlled emissivity/reflection conditions.
- Engine/exhaust regions differ from cold airframes; body/walls occlude interior
  sources. Engine-off cooldown is reproducible after save/reload of thermal state.
- Raw radiance/calibration is independent of display color palette/auto-scaling;
  no RGB-derived heat colors or class-ID shortcut appears in training input.

## SF-07 — LiDAR first-return geometry

Deliver: explicit beam pattern/timestamps, nearest-surface raycast with acceleration,
surface-response/noise pipeline, point-cloud and range preview, sparse raw export.

Acceptance:

- Wall-before-object fixture gives zero hidden-object hits; removing the wall
  restores them. Dropout at the front wall cannot reveal a surface behind it.
- Test partial occlusion, grazing rays, thin geometry, inside/outside face policy,
  arch openings, min/max range, chunk boundaries and empty scans.
- Accelerated results match brute-force triangle intersection on fixed fixtures
  within 1 mm range tolerance away from ties; ties have deterministic policy.
- Point coordinates and camera projection agree with rig transforms. No sampled
  mesh vertices, full-scene point clouds or omniscient depth are fed as LiDAR.

## SF-08 — Weather, time, noise

Deliver: common environment/time state; clear/day/night/fog/rain/snow/hot-background
presets; per-modality atmospheric/noise models; seed and severity controls.

Acceptance:

- At a fixed scene/rig, repeat seeds reproduce output; changing one sensor-noise
  seed leaves scene geometry/placement and other independent noise streams intact.
- Across at least 30 fixed noise seeds, condition sweeps show expected controlled
  RGB SNR/contrast and LiDAR surface-return changes with confidence intervals.
  An IR thermal-crossover fixture verifies contrast loss without imposing a global
  hot-weather penalty. Document cases where the expected trend does not apply.
- Rain/snow produce declared attenuation/particle/blur effects in observations,
  not only decorations in the world view. IR atmospheric attenuation is included.
- Synchronized captures freeze time across all passes. Time jumping vs thermal
  evolution has explicit UI behavior and replayable state.

## SF-09 — Complete catalog and additional environments

Deliver: adapters/catalog records for the remaining supplied aircraft/ground/ship
projects; coast/harbor placement; expanded world/object/camera randomization.

Acceptance:

- All 17 source projects are accounted for with validated import or explicit
  blocked issue. A blocked required asset keeps this item incomplete until an
  adapter is fixed or a documented scope revision is made.
- Ships have correct scale/waterline and are placed in water; aircraft remain
  grounded at aerodromes. Multi-class scenes and background-only scenes exist.
- Per-asset thermal/occlusion fixtures pass and catalog provenance is complete.
  Placement does not encode class through a fixed camera location or condition.

## SF-10 — Visibility labels and dataset jobs

Deliver: per-camera masks/tight visible boxes, 3D boxes, per-object LiDAR counts,
occlusion/truncation/ignore policy, atomic capture publication, grouped splits,
manifest validator, restart/cancel and configurable sample count.

Acceptance:

- At least 24 frozen fixtures cover complete/partial/no occlusion, truncation,
  overlapping instances, narrow openings, dark/foggy yet geometrically visible
  targets, small ignored fragments, empty scenes and distinct sensor viewpoints.
- Masks/boxes/counts match independently specified expected fixture values.
  Fully hidden objects do not become current-frame positives; visible boxes are
  computed from masks, not full projected 3D bounds.
- 300-triple pipeline pilot validates every file hash/shape/unit/calibration;
  report bytes per capture, generation throughput and disk estimates for scale-up.
- No split shares a layout/trajectory/condition-variant group. Detect duplicates,
  interrupted captures, corrupted files and manifest-version mismatches.
- Inference runs unchanged when truth/annotation directories are inaccessible;
  unknown truth-bearing request fields are rejected.

## SF-11 — Learning pilot and baselines

Deliver: 3,000-triple grouped pilot, observation-only dataloader, meaningful 3D
detection evaluation, RGB-only/IR-only/LiDAR-only and simple fusion baselines.

Acceptance:

- Publish class/condition/range/visibility and split counts before training;
  verify no frame-level random splitting or weather-variant leakage.
- Tiny-set overfit test demonstrates end-to-end label/box/loss consistency;
  independent held-out evaluation includes empty scenes and occluded objects.
- All baseline heads predict boxes/classes from observations; neither proposal
  initialization nor input feature computation uses truth boxes/object lists.
- Record loss curves, AP/recall/localization, calibration, runtime and peak memory.
  Save loadable checkpoint, exact preprocessing and dataset hash. Set explicit
  class/condition quality targets for SF-15 using validation, before test access.

## SF-12 — Compact ESSRF

Deliver: `essrf-static-v1` as defined in ESSRF section 0: modality encoders, sparse
discovery/local sampling, evidential reliability, all subset experts and null
abstention. Run pilot training with sampled subset supervision.

Acceptance:

- Test all eight availability patterns: routing sums to one, disabled modalities
  contribute zero, all-missing returns abstention, and no NaN/Inf outputs/gradients.
- Zero positive evidence gives zero supported reliability; ignorance is distinct
  from confident negative evidence. Inputs from excluded modalities do not leak
  through a shared same-frame proposal/query path into subset experts.
- Reliability supervision/calibration targets and OOD exposure are documented;
  weather severity or truth visibility is never supplied at inference.
- Compare to SF-11 on the same validation groups/budget, report failures as well
  as gains, and satisfy memory limits. Do not call this the full temporal ESSRF.
- Update ESSRF with measured choices, losses, query/sample counts and all changes.

## SF-13 — Temporal and calibration dataset extension

Deliver: sequence/trajectory state, per-beam timing, recorded motion and thermal
history, nominal versus actual sensor calibration and controlled drift.

Acceptance:

- Static scenes reproduce the synchronized profile. Moving fixtures validate
  scan-time transforms and expected registration error under known perturbation.
- Sequence replay restores thermal/object/sensor state; frame gaps and timestamp
  disorder are explicit errors or declared handling modes.
- Drift/corruption truth is isolated from model input. Temporal clips and their
  variants stay entirely within one split, with enough length for outage tests.

## SF-14 — Full temporal/calibration ESSRF profile

Deliver: `essrf-temporal-v1`, query bank, motion propagation, uncertainty-aware
local sampling, gated measurement update and null-expert tracking behavior.

Acceptance:

- With all sensors absent, prediction state follows the motion prior, measurement
  correction is exactly zero and measurement processing cannot shrink uncertainty.
  No new objects are invented as observed detections during a full outage.
- Test loss/recovery of each sensor, brief/all-sensor outages, partial local
  corruption, calibration drift, sequence reset and expired track hypotheses.
- Camera covariance/projection checks use finite-difference/analytic fixtures;
  KNN and sample validity handle zero points and off-image references.
- Evaluate temporal/static ablations under identical sequence splits; record
  memory/latency and explicit model-document changes when modifying the proposal.

## SF-15 — Dataset scale-up and trained candidate

Deliver: validation-selected dataset volume, repeatable training, candidate
checkpoint, sealed-test report, corruption/subset/temporal ablations and model card.

Acceptance:

- Use the 3k/10k/30k ladder only when validation curves and coverage justify more
  data; set stopping/resource limits from measured pilot cost. More data is not
  itself a completion criterion. Report the actual chosen sample count/reason.
- Meet quality targets established in SF-11, or document failure and revise the
  model in ESSRF before another validation run. No universal accuracy is promised.
- Compare at least three training seeds for the final comparison; report
  uncertainty and per-condition/class counts. Evaluate every sensor subset,
  all-missing abstention, held-out conditions and held-out assets where feasible.
- Report AP/recall/localization/calibration plus p50/p95 latency and peak allocated/
  reserved/process memory. No tuning on the sealed test set.
- Checkpoint load reproduces saved predictions in its pinned environment; model
  card names scope, synthetic limitations and any unmet requirements.

## SF-16 — Interactive trained-model demo

Deliver: checkpoint-backed inference, tri-modal synchronized display, time/weather/
temperature/heat controls, modality toggles, paired scenario replay, overlays,
metrics and capture/job controls.

Acceptance:

- Changing conditions generates new observations and actual model predictions;
  displayed confidence is never set by weather rules or copied from truth.
- Paired replay preserves object state and rig while changing the chosen
  condition. Predictions/frames share capture IDs; stale inference is discarded.
- Missing/incompatible checkpoint, backend failure, all-empty/all-missing sensors
  and cancelled jobs have correct explicit states. Ground truth is separately
  labeled and hidden by default.
- Browser QA covers daylight, night, fog, precipitation, thermal crossover,
  sensor outages, navigation, export and job cancellation. Demonstrate measured
  behavior even where model outcomes differ from expectations; do not hide it.

## SF-17 — Delivery and regression closure

Deliver: clean-checkout setup/run/generate/train/evaluate instructions, versioned
small fixtures, artifact download/export instructions, source/artifact manifests,
full regression results and recorded browser demo.

Acceptance:

- Reproduce one world, one labeled tri-modal capture, tiny training run, checkpoint
  reload and inference without access to the original external model directory.
- Run the complete contract/world/sensor/dataset/model/API/browser suites plus
  declared performance and memory checks. Record failures and limits explicitly.
- Verify artifact hashes and model-document consistency; all user-request rows
  above have acceptance evidence. No task is DONE solely from a screenshot/loss.
- Commit/push documentation and evidence, verify remote HEAD and clean worktree.

## Deferred extensions

After the required lab is accepted: measured sensor calibration, multi-return
LiDAR and transmissive materials, fine-grained aircraft classes, more complex
motion/weather, distributed generation, and sim-to-real evaluation. These are
separate tasks; their absence must be visible in capability/model descriptions.
