# SF-02 connected world verification

Date: 2026-09-21. Implementation starts from SF-01 closure `690ed6b`.
The final verification manifest identifies the tested implementation revision
and source Git-blob hashes without requiring a self-referential evidence commit.
No GitHub workflows were executed for this stage.

## Delivered behavior

`@yulab/world` owns the validated, immutable world snapshot, global field,
chunk addressing/meshing and independently seeded procedural placement.
The legacy generator moved behind its separate package entry point, preserving
all four preset geometry/color hashes and decoration counts captured before the
move. The editor links to a production-built four-chunk connected-world view.
See [world profile](../WORLD_GENERATOR.md) for semantics and explicit limits.

## Local checks

Environment: Windows, Node 25.6.1, npm 11.9.0, uv 0.12.17, isolated Python
3.13.10; locked npm/uv dependencies. Browser: Microsoft Edge 153.0.4234.32 via
Playwright 1.63.0, explicitly selected with `PLAYWRIGHT_CHANNEL=msedge` and
software WebGL. Host GPU: RTX 3090, driver 32.0.15.9186; these runs do not
benchmark the GPU or establish SF-03 frame-time/resource targets.

| Command | Exit | Result |
| --- | --- | --- |
| `npm install --package-lock-only --ignore-scripts` | 0 | World workspace/dependency lock updated |
| `npm install --offline --ignore-scripts` | 0 | Workspace symlink installed from local cache |
| `npm run verify` | 0 | Generated contracts unchanged; TypeScript; 62 contract checks, 7 world tests, 72 Python checks; production build |
| `npm run verify:world` | 0 | Two complete 256-chunk worlds, all seam/topology/coverage checks, shuffled replay |
| `PLAYWRIGHT_CHANNEL=msedge npm run test:browser` | 0 | All 7 tests against development server, 45.7 s |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_TEST_BUILT=1 npm run test:browser` | 0 | All 7 tests against built production HTML, 45.1 s |
| `npm run typecheck` | 0 | Final browser-run configuration and all workspace/test/tool sources |
| `git diff --check` | 0 | Whitespace verification |

Browser environment assignments above use POSIX notation for brevity; on
Windows they were set using `$env:NAME='value'`. Browser tests own fresh local
servers and exercise the actual backend proxy. Existing two upstream Python
test-client deprecation warnings remain; no failing check was suppressed.

## Full-domain results

Each world spans X/Z [-1024,1024), uses 128 m chunks and a 4 m lattice. It was
generated in lexicographic order and again in deterministic shuffled order from
a fresh world snapshot. Every geometry/normal/color and placement hash matched.
Records preserve the per-chunk hashes:
[seed zero](sf02-world-seed-0.json), [default seed](sf02-world-seed-48291.json).

| Seed | Chunks | Neighbor seams | Vertical probes | Triangles | Unique rock IDs |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 256 | 480 | 262,144 | 2,185,224 | 1,531 |
| 48291 | 256 | 480 | 262,144 | 2,182,296 | 1,541 |

Shared boundary vertex sets, normals and colors match exactly (declared position
tolerance 0.0001 m). Welded interior triangle edges have incidence two and
opposite winding; incidence-one edges occur only at the declared chunk faces.
Vertical probes rasterize actual triangles independently of the density field;
all find terrain. No duplicate placement IDs occur across the full domain.
Generation/verification durations in JSON include test overhead and are not
interactive performance claims.

Focused independent Moller-Trumbore tests on actual triangles establish a clear
through-arch ray, clear separate tunnel ray, bottom and top of a ledge, and an
enclosed cavity whose front wall occludes its interior. Both 2 m and 4 m meshes
pass. Additional tests cover negative/zero chunk boundaries, seed changes,
feature order, frozen input isolation, malformed profiles, finite/unit normals
and base coverage at both extremes of the world.

## Browser inspection

The seven browser tests include the original presets, seed editing, orbit,
zoom/top/reset, real PNG/OBJ/GLB downloads, backend failure/recovery and mobile
layout. Connected-world checks cover the editor link, seed 0 -> 48291 -> 0
pixel-identical replay, four regions, camera presets and boundary overlay.

Visually inspected desktop oblique, seam overlay, ground-level arch/tunnel,
ridge and mobile screenshots. No cracks or abrupt seam lighting/material bands
were observed. The ground-level image shows the arch opening, right-side tunnel
and unsupported ledge underside. The rectangular preview edge is the explicitly
declared four-chunk residency boundary, not an isolated diorama base per chunk.
Screenshots are local ignored artifacts under `artifacts/browser/`; their hashes
are in the final manifest. No prior pixel baseline or physical realism is claimed.

## Failures retained and resolved

- Initial test-first run failed with missing `packages/world/src/index.ts`;
  retained in `artifacts/sf02/red-world.log`.
- The triangle tunnel test caught an overlapping arch refilling a subtraction.
  Subtracting tunnel/cavity after rock union fixed it; both mesh pitches pass.
- Full-world topology inspection caught reversed faces at sharp CSG gradients
  and sub-Float32 slivers close to lattice nodes. Winding now follows sampled
  solid/air separation, with a deterministic 0.01 density tie band. The original
  failure is retained in `artifacts/sf02/red-winding.log`. Both complete seed
  sweeps pass without relaxing the topology assertions.

## Scope limits

The connected feature forms are intentionally new, bounded world-space
definitions. The legacy editor's characterized output is unchanged. Islands
retain ground below them; coastal bluffs have no simulated sea/harbor yet.
Normals and colors use continuous global fields while the surface stays coarse.
Boundary tolerance is distinct from analytic-surface approximation error.

Preview residency is four fixed chunks. Streaming, navigation, mixed-pitch LOD,
sensor residency, cancellation and measured resource bounds are SF-03. Asset
imports/contact validation are SF-04. There are no sensor, capture, dataset or
model capabilities added by SF-02. The world API rejects unsupported types and
versions rather than silently substituting geometry.
