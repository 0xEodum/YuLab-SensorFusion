# Connected world profile

Quality status (2026-09-21): SF-02R corrects the flat SF-02 presentation with
multi-scale ground relief, 16 seeded regional formations, richer density detail,
trees, rocks and flat-shaded low-poly rendering. Recorded browser views compare
all four families with the legacy scenes at landmark-detail scale and show
multi-chunk overviews for three fixed seeds. The new regions preserve the visual
language and readable openings while remaining generated landscapes rather than
copies of the handcrafted dioramas.

SF-02R implements `connected-world.v2` / `connected-field.v2` in `packages/world`.
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
- V2 accepts at most 2,048 m per horizontal axis with endpoints within ±4,096 m.
  The vertical interval is fixed. Other profiles fail rather than silently
  changing resolution or cropping features.
- Seed zero is valid; seeds are uint32. No truthy fallback or global RNG is used.
- World IDs are limited to 64 characters, leaving room for placement IDs within
  the wire contract's 96-character limit. Feature IDs must be unique.
- Imported asset instances, aerodromes and harbors are rejected until their
  implementation stages. The backend still implements only health/capabilities;
  this local package does not advertise an implemented world-job API.

## Field, biomes and features

Positive density is solid. Continuous base elevation combines a 410 m domain
warp with broad 510 m relief, 235 m ridges, 112 m hills and 34 m local detail.
It is centered near 19 m and clamped to 2..58 m. There is no local island
envelope or per-chunk edge falloff. Feature union cannot remove the ground.

The biome field blends warm grass/stone into cooler vegetation/stone using a
warped 360 m field. Slope, elevation and 10 m surface noise continuously blend
linear RGB vertex colors; height-dependent strata add material variation. The
biome definition belongs to the field version, rather than a random palette
independently selected per chunk.

The default specification divides the domain into a 4 × 4 regional lattice.
Each seed deterministically jitters centers and extents, rotates the family
ordering, and derives an independent feature seed, producing four examples of
each supported form. Feature centers and full XYZ extents remain explicit in
`WorldSpec.features`:

| Type | Geometry |
| --- | --- |
| canyon | Warped arch/ring, asymmetric abutments and shelves, through-tunnel and enclosed cavity |
| alpine | Three overlapping, seed-shifted ridge/peak volumes with amplified surface breakup |
| islands | Three overlapping highland outcrops with overhangs above continuous ground |
| coast | Irregular rounded bluff/mesa and stacks; water/harbor simulation remains SF-09 |

Dimensions are 64..256 m per axis and must fit the domain with 8 m vertical
clearance. Lower bounds retain multiple samples through supported openings.
Features cross chunk faces without changing definition. Domain warps plus
coarse, fine and stratified 3D noise break up surfaces without affecting chunk
ownership. Subtractive tunnel and cavity operations apply after rock union so
overlapping masses cannot refill them. The base takes priority: placing an
opening below ground buries it.

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
neighboring meshes is unsupported. SF-03 implements display LOD by atomically
swapping the complete neighborhood between these pitches; it never mixes them.

There are no internal chunk sidewalls, skirts, stretched bases or hidden ground
planes. The outer world boundary and current resident-neighborhood boundary are open cuts
through the finite domain, not container walls. The solid base extends below
the sampled domain. Future capture residency/range handling must respect the
finite-domain limits.

## Placement and preview

Procedural candidates use independent hash channels on 16 m global cells with
half-open chunk ownership. IDs combine world ID, kind and signed global cell
coordinates; requests consume no shared RNG. A top-surface field intersection,
slope, height and biome tests deterministically choose trees or rocks and reject
unsuitable cells. The preview renders layered low-poly conifers and irregular
dodecahedral rocks. These remain procedural decoration, not imported asset
instances. Field support and coarse display triangles can differ by
discretization error; asset contact validation belongs to SF-04.

The editor's **Explore the connected world** link opens `?view=world`: a moving
3 ? 3 neighborhood with seed controls, 16 region shortcuts, overview/detail/top/
opening views, free flight, rig bookmarks, display-detail selection and an actual
shared-edge overlay. Workers generate chunks; the LRU cache reuses neighbors and
cancels superseded work. The renderer instances decorations per chunk and disposes
replaced geometry. [STREAMING.md](STREAMING.md) defines bounds, LOD, cancellation,
bookmark frames, sensor range coverage and local acceptance.

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
Reports: `artifacts/sf02r/world-verification-<seed>.json`. All checks are local;
no GitHub workflow is needed or configured.
