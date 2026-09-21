# Connected world profile

SF-02 implements `connected-world.v1` / `connected-field.v1` in `packages/world`.
The public entry point generates typed mesh arrays and procedural placement
records without a renderer or resident-neighbor state. `@yulab/world/legacy`
preserves the original Three.js preset generator; `frontend/src/terrain.ts` is
its compatibility facade. Shared seeded noise retains the original algorithm.

## Snapshot and coordinates

`createWorld(WorldSpec)` validates the canonical `lab.v1` wire schema and the
narrower supported generator profile, copies the input, sorts features by ID,
and recursively freezes the snapshot. Caller mutation cannot change an existing
world. Unknown generator/field versions fail explicitly.

- Metres, right-handed +X east, +Y up, +Z south.
- Default extent: X/Z `[-1024,1024)`, Y `[-32,96]`. The 16 × 16 grid covers
  2,048 × 2,048 m; chunk coordinates run from -8 through 7 on each axis.
- Chunk size is 128 m; addressing is `floor(worldCoordinate/128)`, including
  negative positions. Horizontal origins/extents align to this global lattice.
  Chunks own half-open areas; meshing includes both boundary faces.
- V1 accepts at most 2,048 m per horizontal axis with endpoints within ±4,096 m.
  The vertical interval is fixed. Other profiles fail rather than silently
  changing resolution or cropping features.
- Seed zero is valid; seeds are uint32. No truthy fallback or global RNG is used.
- World IDs are limited to 64 characters, leaving room for placement IDs within
  the wire contract's 96-character limit. Feature IDs must be unique.
- Imported asset instances, aerodromes and harbors are rejected until their
  implementation stages. The backend still implements only health/capabilities;
  this local package does not advertise an implemented world-job API.

## Field, biomes and features

Positive density is solid. Continuous base elevation is the sum of two seeded
world-space noise fields with wavelengths 260 and 65 m, centered at 12 m and
bounded between 3 and 21 m. There is no local island envelope or per-chunk edge
falloff. Feature union cannot remove the ground.

The biome field blends warm grass/stone into cooler vegetation/stone using
420 m world-space noise. Slope, elevation and 12 m surface noise continuously
blend linear RGB vertex colors. The biome definition belongs to the field
version, rather than a random palette independently selected per chunk.

Feature centers and full XYZ extents are explicit world-space values in
`WorldSpec.features`. Supported forms:

| Type | Geometry |
| --- | --- |
| canyon | Elliptical arch, abutments, through-tunnel, ledge underside, enclosed cavity |
| alpine | Overlapping noise-shaped ridge volumes |
| islands | Elevated ellipsoid outcrops above continuous ground |
| coast | Bounded bluff; water/harbor simulation remains SF-09 |

Dimensions are 64..256 m per axis and must fit the domain with 8 m vertical
clearance. Lower bounds retain multiple samples through supported openings.
Features cross chunk faces without changing definition. Subtractive tunnel and
cavity operations apply after rock union so overlapping masses cannot refill
them. The base takes priority: placing an opening below ground buries it.

These are new bounded feature definitions, not enlarged legacy meshes. The
legacy editor retains its original isolated dioramas with unchanged geometry/
color hashes and placement counts for all four presets. In connected worlds,
islands have ground below them and coast means a bluff without the decorative
water disc. These characterization differences are intentional.

## Mesh and seam policy

`meshChunk(world, {x,z}, cellSize)` supports 4 m cells (default) and 2 m cells.
It samples the global integer lattice and uses a consistent six-tetrahedron
split per cube. Shared faces have the same diagonal. Edge interpolation orders
endpoints canonically. Positions, normals and colors are Float32 arrays in
absolute world coordinates.

A deterministic tie policy maps sampled densities with magnitude below 0.01 to
+0.01, avoiding sub-Float32 sliver triangles near lattice corners. This is a
density-space tie band, not a claim of 1 cm surface accuracy. Winding follows the
sampled tetrahedron's solid-to-air direction independently of smoothed normals.
Normals use a 0.05 m central difference of the global field at the stored vertex;
colors use that same position and normal.

The equal-pitch **boundary tolerance is 0.0001 m**. Recorded fixtures match
exactly, including normals and colors. This is not an analytic-surface error
bound. Features remain coarse polygonal approximations. Mixing 2 m and 4 m
neighboring meshes requires transition meshes and is unsupported; LOD is SF-03.

There are no internal chunk sidewalls, skirts, stretched bases or hidden ground
planes. The outer world boundary and four-chunk preview boundary are open cuts
through the finite domain, not container walls. The solid base extends below
the sampled domain. Future capture residency/range handling must respect the
finite-domain limits.

## Placement and preview

Procedural rock candidates use independent hash channels on 32 m world cells
with half-open chunk ownership. IDs combine world ID, purpose and signed global
cell coordinates; requests consume no shared RNG. A top-surface field
intersection sets elevation and a slope check rejects steep placements. These
are procedural rocks, not imported asset instances. Field support and coarse
display triangles can differ by discretization error; asset contact validation
belongs to SF-04.

The editor's **Explore the connected world** link opens `?view=world`: four fixed
chunks, seed controls, four regions, camera presets and an overlay of actual
shared mesh edges. It uses the same package as numerical acceptance. Region
changes replace the entire preview; this is not streaming, cache/LOD acceptance
or a performance benchmark.

## Local verification

```powershell
npm run verify
npm run verify:world
$env:PLAYWRIGHT_CHANNEL='msedge' # omit for installed Playwright Chromium
npm run test:browser
```

`verify` covers legacy characterization, schema/profile rejection, negative
addressing, input isolation, seed/feature/request order, both seam axes and
attributes, and independent double-sided triangle ray tests. Arch/tunnel,
underside and cavity checks run at both cell sizes.

`verify:world` generates all 256 chunks for seeds 0 and 48291, checks triangle
edge incidence/winding, tests 262,144 vertical surface probes per seed, checks
all 480 neighbor boundaries, and recreates the world in shuffled request order.
It compares geometry/normal/color and placement SHA-256 hashes and ID uniqueness.
Reports: `artifacts/sf02/world-verification-<seed>.json`. All checks are local;
no GitHub workflow is needed or configured.
