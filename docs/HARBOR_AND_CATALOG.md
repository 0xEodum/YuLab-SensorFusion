# SF-09 catalog and harbor world

SF-09 adds twelve assets to the three SF-04 imports, for **15 self-contained
catalog records**. The source set supplied for this stage has 17 project
directories. The user revised the required import scope to the 15 complete
projects on 2026-09-24 after inspection found two incomplete sources:

- `aircraft/b-52-model` imports `./Aircraft` from `src/components/Scene.tsx`,
  but `src/components/Aircraft.tsx` is absent.
- `aircraft/mirage-2000-model` has geometry helpers, while `src/App.tsx` is
  still a placeholder and no assembled aircraft component exists.

These two are recorded as excluded supplied projects. Neither is represented
by a surrogate asset. A corrected source can be assessed in a later scoped
item. The 15 imported records are:

| Catalog ID | Supplied project | Class | Width × height × length (m) |
| --- | --- | --- | ---: |
| `f16` | `aircraft/f-16-aircraft` | aircraft | 9.240 × 5.000 × 16.350 |
| `rq4` | `aircraft/rq-4-uav` | aircraft | 39.920 × 4.496 × 15.100 |
| `ground-vehicle` | `AA/fk-2000-3d-model` | ground vehicle | 4.260 × 5.850 × 11.082 |
| `cruiser` | `ships/guided-missile-cruiser-model` | ship | 23.200 × 45.200 × 181.100 |
| `destroyer` | `ships/missile-destroyer-model` | ship | 20.800 × 56.009 × 180.000 |
| `a10` | `aircraft/a-10-model` | aircraft | 17.720 × 5.485 × 17.390 |
| `f14` | `aircraft/f-14-model` | aircraft | 19.820 × 5.885 × 22.575 |
| `f16xl` | `aircraft/f-16xl-aircraft-3d-model` | aircraft | 10.517 × 5.115 × 19.310 |
| `f18` | `aircraft/f-18-3d-model` | aircraft | 11.822 × 5.322 × 19.000 |
| `f22` | `aircraft/f-22-model` | aircraft | 13.600 × 4.213 × 21.950 |
| `mq9` | `aircraft/mq-9-uav-model` | aircraft | 20.020 × 3.407 × 11.735 |
| `su35` | `aircraft/su-35-3d-model` | aircraft | 15.300 × 6.317 × 24.850 |
| `complex-radar` | `AA/modular-air-defence-complex-model` | ground vehicle | 5.040 × 10.272 × 12.869 |
| `simulation-radar` | `AA/modular-air-defense-simulation` | ground vehicle | 3.298 × 4.046 × 8.220 |
| `spaa` | `AA/modular-spaa-3d-model` | ground vehicle | 6.110 × 4.545 × 8.930 |

The importer evaluates allowlisted static components and their audited `src`
dependencies in a pinned browser. It does not run source apps, frame callbacks,
effects or simulation loops. It freezes one visible model configuration per
project, including a phased radar from the complex and a radar vehicle from
the simulation project; other configurations in those projects are not catalog
records. It preserves authored geometry proportions at one metre per source
unit, rotates axes as needed and records file hashes, bounds, ground contacts,
waterline, mesh counts and frozen pose in each sidecar. Semantic thermal regions
and synthetic coefficients are attached to exterior meshes. The F-22 source
has no landing gear; its static model is in the catalog but it is intentionally
absent from grounded airfield rosters. Sidecar contact points for that model
describe geometric low points, not wheels. Source dimensions and thermal
coefficients are research simulation values, not certified physical data.

Run `npm run assets:import -- "K:\PycharmProjects\world_models\Generated"`
to rebuild `frontend/public/catalog/`. An optional second argument writes to a
separate output directory. The normal app, build and tests use committed GLB
and metadata files without the external source tree. The importer is pinned to
the Edge software canvas path for reproducible livery rasterization; local
reimport compares all 31 catalog files byte for byte.

## World profiles

The world toolbar provides the existing natural landscape and aerodrome
fixtures, plus an **Airfield mix**, **Empty airfield**, **Coast & harbor** and
**Empty harbor**. A seeded airfield mix chooses four grounded aircraft and two
ground vehicles from the available rosters, then varies stand position and
yaw. The 24.04 m apron contact plane is unchanged. The empty profile provides
the same graded infrastructure without instances. `New viewpoint` samples
distinct seeded camera poses without changing the world or object identities.
The existing aerodrome fixtures remain the stable SF-04 occlusion cases.

`harbor-world.v1` / `harbor-field.v1` grades a continuous coast from a submerged
basin to a 14 m quay. Water is at 6 m world Y. The cruiser and destroyer each
have a 0 m model waterline and a rigid 6 m Y translation, leaving keels below
water and superstructures above. Their seeded berths vary within separate
slots without intersecting shore, piers or each other. Quay walls, piers,
breakwaters, beacons, cranes, container stacks, offices and warehouses give
the port a legible low-poly silhouette. A world-wide 16 m water grid with
subtle vertex color and wave variation reaches the horizon independently of
display chunk residency. The display and sensor scene builders use this same
site geometry. The empty harbor retains the port and water with no ships.

## Verification boundary

Asset tests check GLB integrity, provenance, semantic mesh references, normals,
dimensions and contacts for all 15 records. A first-return fixture takes a
nondegenerate triangle from every GLB and checks its asset class and a nearer
occluder. Thermal tests run off, idle and
running equilibrium for every record. Seeded placement tests cover aircraft,
ground vehicles and ships. Browser QA measures projected-triangle visibility
for both harbor ships and the six seed-zero airfield instances, checks harbor
sensor residency and saves matched-scale screenshots. SF-04 clear, partial
and hidden hangar occlusion fixtures remain in the browser regression suite.
These checks establish the deterministic catalog and scene behavior on the
tested local renderer. They do not establish real-world radar or thermal
signatures, hydrodynamics, sensor labels or model training quality.
