# SF-02R procedural landscape quality evidence

Date: 2026-09-21. Verification policy: local only, by user instruction. No
GitHub workflow was created or run. Implementation checkpoint: `c21a562`.
Artifact hashes are recorded in
[`sf02r-verification-manifest.json`](sf02r-verification-manifest.json); the
earlier SF-02 v1 reports and hashes remain unchanged.

## Result

The `connected-world.v2` / `connected-field.v2` profile replaces SF-02's nearly
flat four-landmark presentation with a continuous multi-scale terrain field and
16 seed-generated regions. Every default world contains four canyon, alpine,
highland-outcrop and coast formations distributed over the 2,048 × 2,048 m
domain. Feature position, extent, density warp and surface detail change with
the world/feature seeds. The fixed preview now shows a 3 × 3 chunk neighborhood
with low-poly terrain, trees and rocks around any generated region.

The original editor remains characterized by its existing geometry, color and
placement hashes. The correction changes only the connected profile and bumps
both generator and field versions so v1 evidence is not silently reinterpreted.

## TDD checkpoints

| Commit | Gate | Result |
| --- | --- | --- |
| `00134ae` | RED: regional feature count/distribution, relief and feature-seed geometry tests | Three expected failures |
| `d538637` | GREEN: multi-scale terrain and 16 seeded regional formations | 10 world tests passed |
| `21ffcf7` | RED: deterministic tree and rock placement | One expected failure |
| `9073182` | GREEN: stable 16 m-cell decoration | 11 world tests passed |
| `632a23c` | RED: 16 regions, nine chunks, trees/rocks and >30k preview faces | Browser contract failed against old preview |
| `c21a562` | GREEN: generated-region explorer, comparison captures and v2 verifier | Unit, browser and type checks passed |

## Legacy/current visual assessment

The browser suite captured the original Canyon, Alpine, Islands and Coast
canvases, then the connected v2 equivalent at both 384 m overview and
landmark-detail framing. Connected canyon overview/detail views were also
captured for seeds 0, 48291 and 77123. Direct image inspection produced these
findings:

| Aspect | Finding |
| --- | --- |
| Formation shape | Canyon keeps a large through-opening, asymmetric shelves, abutments and an enclosed cavity. Alpine forms a broad multi-peak ridge. Outcrops retain separate overhanging masses above continuous ground. Coast forms a rounded irregular bluff with stacks. Seed changes visibly alter silhouette, height, orientation and surrounding biome. |
| Ground relief | All nine preview chunks carry rolling regional elevation, ridges/valleys and smaller undulation; the former flat slab is gone. Relief and landmark geometry cross chunk boundaries continuously. |
| Surface detail | Flat-shaded 4 m triangles expose low-poly facets. Domain warping, coarse/fine 3D noise and height strata break up formation surfaces. Deterministic layered conifers and irregular rocks add scale and local detail. |
| Materials | Slope/elevation, biome and strata fields produce continuous grass/stone transitions across seams. The result is more gradual than the legacy editor's deliberately patchy color composition, but no longer reads as a single flat material. |

The comparison supports comparable low-poly density detail, readable formation
structure and scene richness at equivalent landmark scale. It does not claim
pixel parity: the legacy scenes are handcrafted isolated compositions, while v2
uses broader generated regions on continuous ground. The alpine and coast
silhouettes remain lower and wider than their legacy counterparts, connected
outcrops deliberately keep terrain underneath, and no water, imported foliage
or asset variation is present yet. Pixel-difference regression is not automated;
the retained captures and manifest hashes are the review evidence.

## Local verification

Environment: Windows, Node 25.6.1, npm 11.9.0, Python 3.13.10, uv 0.12.17,
Playwright 1.63.0 and Microsoft Edge 153.0.4234.48 with software WebGL.

| Command | Exit | Result |
| --- | --- | --- |
| `npm run typecheck` | 0 | Frontend, contracts, world and tools TypeScript passed |
| `npm run test:world` | 0 | 11/11 tests passed |
| `node --experimental-strip-types --experimental-test-coverage --test tests/world/*.test.ts` | 0 | 11/11; 95.86% lines overall, field 99.36%, mesh/placement 100% |
| `npm run verify:world` | 0 | Two complete 256-chunk worlds and shuffled replays passed |
| `npm run verify` | 0 | Contract drift, TypeScript, 62 contract, 11 world, 72 backend tests and production build passed |
| `PLAYWRIGHT_CHANNEL=msedge npm run test:browser` | 0 | 8/8 development-server browser tests passed in 1.6 min |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_TEST_BUILT=1 npm run test:browser` | 0 | 8/8 production-built browser tests passed in 1.5 min |

The browser tests cover the real backend states, unchanged legacy editor/export,
seed zero, seed regeneration, all 16 location options, actual shared-edge
overlay, opening/detail/top/overview cameras, legacy/current captures and narrow
viewport behavior. No page errors or WebGL failures occurred.

## Full-domain and preview cost

| Seed | Chunks | Seams | Vertical probes | Triangles | Placements | Elapsed |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 256 | 480 | 262,144 | 2,500,574 | 9,074 | 81.1 s |
| 48291 | 256 | 480 | 262,144 | 2,500,656 | 9,150 | 80.2 s |

The seed-zero Alpine preview recorded 95,022 faces, 198 trees, 114 rocks and
1,272 ms generation for nine chunks in the software-WebGL browser run. This is
an acceptance measurement, not an SF-03 frame-time or cache target. The preview
still regenerates a fixed neighborhood when the region changes. Worker
generation, cancellation, bounded caching, display LOD, free navigation and
sensor residency remain SF-03.

## Closure

SF-02R is DONE. SF-03 is the sole READY item. This closure adds no sensor,
capture, dataset or model capability and makes no GPU-performance claim.
