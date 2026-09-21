# Imported assets and the first aerodrome

SF-04 adds `static-model.v1`, `asset-catalog.v1`, `asset-import.v1` and
`aerodrome-world.v1` / `aerodrome-field.v1`. The natural `connected-world.v2`
profile and the legacy preset editor retain their existing semantics.

Open the connected world, then **Open aerodrome**. Catalog cards provide close
inspection views; visibility buttons restore fixed inspection poses. Direct
entry: `/?view=world&site=aerodrome`. Flight, seed, detail and bookmarks work in
either profile. Bookmarks are stored separately for landscape and aerodrome.

## Source adapters and scale

`npm run assets:import -- "K:\PycharmProjects\world_models\Generated"`
rebuilds `frontend/public/catalog/`. An optional second argument selects another
output directory for reimport comparisons. The importer uses pinned esbuild /
Three.js and headless Edge (`PLAYWRIGHT_CHANNEL` can select another installed
Playwright browser). Normal build, tests and runtime need no external sources.

Only eight allowlisted model/geometry/livery files are evaluated. Aircraft
adapters evaluate static JSX with memoization and refs; effects and frame hooks
do not execute. The vehicle adapter calls its geometry factory. Source app
entrypoints, cameras, controls, stores, projectiles and simulation loops are
excluded. Existing geometry names are annotated, gear is frozen down and engines
off, and canvas liveries become embedded PNGs. No source project is copied here.

| Asset | Source project | Source forward | Imported width Г— height Г— length |
| --- | --- | --- | --- |
| F-16 | `aircraft/f-16-aircraft` | +X | 9.240 Г— 5.000 Г— 16.350 m |
| RQ-4 | `aircraft/rq-4-uav` | +Z | 39.920 Г— 4.496 Г— 15.100 m |
| 8Г—8 ground vehicle | `AA/fk-2000-3d-model` | -X | 4.260 Г— 5.850 Г— 11.082 m |

All use one metre per authored unit. This is a shared simulation scale, not a
claim of certified real-vehicle dimensions. F-16 length includes its probe.
The vehicle factory labels itself Pantsir-SM despite its folder name; the UI
uses 8Г—8 ground vehicle rather than silently resolving that naming conflict.
Axis rotations preserve proportions without independent axis stretching.
Model-local axes are +X left, +Y up, +Z forward; world axes remain east/up/south.
Instance transforms are rigid and row-major.

The root shifts to the lowest source tread. Sidecars record actual tread
vertices for three aircraft or eight vehicle contacts. Polygonal RQ-4 tyres
have a residual height difference under 3 mm; placement tolerance is 15 mm.
Mirrors are baked into vertices, winding is corrected, back-facing materials
converted explicitly and flat normals baked (glTF has no `flatShading` flag).
Zero-area triangles are removed. GLBs contain no animations, cameras or external
buffer/image references. Named parts and material appearances are retained.

Canonical `AssetRecord` entries identify each GLB and sidecar by SHA-256 and
byte length. Sidecars contain the eight source file hashes and transforms.
Aggregate source hashes cover the ordered file-hash lists. Runtime checks GLB
and metadata integrity and semantic node references. Missing records, HTTP
failures, unsupported metadata and damaged files fail with asset name/reason.
Browser/font canvas rasterization belongs to the import environment; exact
cross-platform PNG identity is not promised. Local reimports are byte-identical.
The import browser explicitly disables GPU/accelerated 2D canvas: automatic
canvas backend switching produced differing tail-livery PNG bytes during QA.
The runtime renderer retains normal GPU rendering. Three independent imports
match after fixing the import raster backend.

## Heat region scope

F-16 rear fuselage/nozzle and RQ-4 nacelle/exhaust retain named engine/exhaust
surface regions. The vehicle has front engine-cover and rear radiator regions;
its source has no separate exhaust mesh. Regions identify exterior surfaces.

`surface-regions.v1` is preparatory metadata: all sources are off with zero
power. Material coefficients are synthetic placeholders, including unit
area/capacity fields. They do not claim computed thermal mass, real signatures,
temperature evolution or IR imagery. SF-06 replaces this profile with validated
thermal parameters/dynamics. RGB canopy transparency is retained; IR/LiDAR
metadata declares an opaque approximation.

## Grading and placement

A flat 448 Г— 1,280 m pad at (64, 24, 0) has a smooth 32 m shoulder. The field
grades terrain itself, suppresses volumetric landmarks within the pad and
excludes trees/rocks through the shoulder. Elsewhere the seeded landscape is
retained. Validation checks fixed site bounds, rigid yaw transforms, unique
identities and world containment.

Infrastructure: 1,200 Г— 40 m runway, parallel taxiway, three connectors, apron,
markings, two hangars, tower, road and perimeter posts. Hangar walls/roofs are
separate volumes; one entrance is partly open and the other closed. This is a
simulation layout, not an operational airfield specification. Exposed aircraft
and vehicle placements vary deterministically with seed; hangar fixtures stay
fixed. Instance IDs do not depend on residency or request order.

Pavement and tyre contacts share elevation 24.04 m, 4 cm above graded terrain.
Tests check each asset box against other assets and walls, contacts against
ground and runway height across chunk boundaries. Both hangar aircraft fit
without wall/roof intersections. Long pavements are clipped to resident chunks;
the wide view intentionally shows only the streamed neighborhood.

## Residency and fixtures

`@yulab/assets` owns catalog loading, shared model templates and
`buildAerodromeScene`. Three templates load once (about 12.75 MB GLB data).
Compatible materials are batched within each semantic region; clones share
geometry/textures. Infrastructure buffers are disposed on neighborhood changes;
profile/seed changes and unmount dispose templates and textures.

Asset/building membership uses transformed bounds against every resident chunk,
including cross-boundary wings/buildings. Long surfaces are clipped per chunk.
The independent fixed-2-m sensor lease builds the same asset/infrastructure
geometry from its own chunks. Display frusta never control sensor membership.
The existing 8 m terrain-decoration margin is not substituted for asset bounds.

Fixtures cover an unobstructed F-16, partial hangar occlusion and a fully hidden
F-16. Acceptance casts a 40 Г— 32 projected-target grid of rays against rendered
triangles and compares against the isolated target. This is geometry fixture
verification, not a capture pass, dataset label or implemented sensor; SF-05
introduces capture. Source use is authorized by the user's supplied catalog;
no independent third-party licensing claim is made.
