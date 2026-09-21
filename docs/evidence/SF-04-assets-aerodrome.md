# SF-04 asset import and aerodrome evidence

Date: 2026-09-21. Implementation: `2102fc07a23ff6b095adf3df09a11351fda1c765`.
Local acceptance passed. Source files, runtime bundle, fixtures, build outputs,
logs and screenshots are identified by the
[verification manifest](sf04-verification-manifest.json). Source hashes refer
to Git blob bytes at that implementation revision; artifact hashes refer to raw
bytes. The subsequent evidence commit does not claim a self-referential hash.

## Delivered and inspected

F-16, RQ-4 and one 8×8 vehicle are imported from the supplied React/Three.js
projects into self-contained GLBs with embedded materials/textures and physical
sidecars. Four independent imports produce identical bytes for all seven bundle
files. Eight original source files retain individual SHA-256 identities.
Source apps, animation loops, controls, stores and projectiles are excluded.

The assets share metre scale, +Y up and +Z forward (+X left relative to heading).
Uniform scale 1 preserves source proportions. Full dimensions are F-16
9.240 × 5.000 × 16.350 m, RQ-4 39.920 × 4.496 × 15.100 m and vehicle
4.260 × 5.850 × 11.082 m (width × height × length). Tests independently read GLB
positions/normals and check finite data, unit normals, reflected winding,
triangle counts, semantic nodes, bounds and real tyre contacts. The RQ-4's
polygonal tyres have a 2.94 mm inter-wheel height residual, within 15 mm tolerance.

The seeded aerodrome has a graded pad/shoulder, runway, apron, taxiway/connectors,
markings, open/closed hangars, tower, road and perimeter posts. Five stable
instances are placed without asset/asset or asset/building intersections.
Contacts sit on pavement at 24.04 m over terrain at 24 m. Vegetation is excluded
from the graded site. Infrastructure and objects share display/sensor scene
construction; bounds-based residency includes cross-boundary geometry.

The catalog has inspection controls and named visibility poses. Runtime failures
name missing/corrupt GLBs, sidecars or required catalog records, with no substitute
model. Actual browser screenshots were inspected for recognizable aircraft and
vehicle geometry, livery retention, relative scale, contacts, hangars and occlusion:

| Overview | F-16 | RQ-4 | Vehicle |
| --- | --- | --- | --- |
| [Aerodrome](sf04/aerodrome.png) | [F-16](sf04/f16.png) | [RQ-4](sf04/rq4.png) | [8×8](sf04/ground-vehicle.png) |

No pixel-baseline equivalence or certified real-vehicle dimensions are claimed.
The source folder/vehicle factory naming conflict is documented in
[asset semantics](../ASSETS_AND_AERODROME.md).

## Acceptance results

| Check | Exit | Result |
| --- | --- | --- |
| `npm run assets:import -- <Generated> [output]` | 0 | Four independent CPU-canvas exports match all seven artifacts |
| `npm run verify:world -- --aerodrome` | 0 | Seeds 0/48291: 256 chunks, 480 seams, 262,144 coverage probes each; topology and shuffled replay pass |
| Fresh source archive: `npm ci`, `npm run backend:sync` | 0 | Fresh npm dependencies and isolated backend environment |
| Fresh source archive: `npm run verify` | 0 | Typecheck, contract drift, 62 contract + 19 world + 4 asset + 72 backend tests, production build |
| Fresh source archive: Edge GPU production browser suite | 0 | All 13 tests, including asset errors/fixtures, editor/export/API regressions and 104-boundary traversal |
| Edge software development compatibility suite | 1, then isolated rerun 0 | 11/12 initially pass; one existing visual predicate times out under concurrent CPU verification; unchanged isolated case passes |

The fresh archive is `artifacts/sf04/sf04-source.zip`, extracted into
`artifacts/sf04/clean-2102fc0`. It contains the catalog bundle and no source model
projects. All core/browser commands above run from that fresh tree; no model
import command or external Generated directory is required at runtime.
The test/browser scripts have no external model path dependency. Global uv
0.12.17 was supplied on PATH, as permitted by setup instructions.

Fixed-grid triangle-ray fixtures on production geometry give:

| Fixture | Isolated target hits | Visible hits | Visible fraction |
| --- | ---: | ---: | ---: |
| [Unobstructed](sf04/clear.png) | 150 | 150 | 1.000 |
| [Partial hangar](sf04/partial.png) | 213 | 92 | 0.432 |
| [Closed hangar](sf04/hidden.png) | 112 | 0 | 0.000 |

Independent sensor residency includes the hidden aircraft and closed door.
Repeated travel away/back restores all instance IDs and identical GPU geometry/
texture counts; shared templates remain bounded at three. Natural-world
regression crosses 104 adjacent boundaries and checks 1,260 seam pairs. Its
frame p50/p95 is 16.7/16.9 ms at 1280 × 720 on RTX 3090. Asset inspection reports
16.7/16.9 ms at 1358 × 620; the maximum frame is 316.7 ms during loading/inspection
work, so these percentiles are not a promise of zero loading stalls.

## Failures retained and resolved

- Initial catalog test is RED because the bundle does not yet exist; its log is
  retained. Import-only TypeScript/JSX adapter issues were corrected before use.
- Accelerated canvas selected differing raster paths for RQ-4 tail texture PNGs.
  Fixing the import browser to CPU canvas produces four matching exports.
  Normal runtime rendering still uses GPU acceleration.
- The first development GPU traversal failed its strict heap-nondecrease
  predicate, although absolute heap/cache/disposal limits passed. Both isolated
  and complete production traversals passed the unchanged predicate. Additional
  heap diagnostics are now retained even when that gate fails.
- The initial new software asset test read the previous ready neighborhood before
  the next animation frame began streaming. Its helper now waits for the requested
  chunk coordinates as well as readiness. Final asset checks pass on GPU and
  software renderers. A separate pre-existing world visual-change predicate timed
  out while software QA shared CPU resources with full-world verification; its
  unchanged isolated rerun and final production run pass. Failure logs remain
  alongside the passing evidence rather than being overwritten.

## Boundaries

The three imported projects are SF-04's scope; the remaining catalog belongs to
SF-09. Poses are static. Engine/exhaust/radiator surface names and off-state heat
metadata are preparations for SF-06; area/capacity coefficients remain documented
synthetic placeholders. There is no IR, LiDAR, capture pipeline or trained model
in this stage. Ray fixtures validate geometry, not dataset annotations.

The finite display neighborhood clips the long runway/road to resident terrain;
it does not render the entire 1,200 m runway at once. Import PNG identity is
verified on the recorded Windows/Edge/font environment, not every platform.
These limits do not remove an SF-04 requirement. SF-05 is the next READY task.
