# SF-06 surface heat and thermal IR evidence

Date: 2026-09-22. Tested implementation:
`14b65365a69958b9518cc4d4d696b5bd81a2a30e`. Local acceptance passed. Exact
machine-readable results and retained artifact identities are in the
[verification manifest](sf06-verification-manifest.json). The later evidence
commit does not claim a self-referential source hash.

## Delivered and inspected

`thermal-surface.v1` replaces the placeholder asset metadata with positive,
semantic surface coefficients and rated engine/exhaust/radiator sources. The
world snapshot selects off/idle/running state. The pure sensor core aggregates
parts into semantic nodes, solves equilibrium, advances the documented energy
balance with deterministic fixed steps and serializes `thermal-state.v1` for
continued capture.

`lwir-8-14um.v1` forms band-integrated gray-body radiance from temperature,
emissivity and ambient reflected radiance, then applies a seeded detector-noise
and saturation profile. The Chromium pass uses the calibrated IR camera and
ordinary depth testing over the same resident geometry. It ignores RGB lights,
visual colors and instance IDs. Internal power heats exterior nodes; it is not
rendered as visible geometry through bodies or walls.

IR jobs atomically add float32 radiance, boolean validity/saturation, fixed-scale
preview and thermal-state artifacts. Calibration records units, band, response,
noise, saturation, thermal versions and that the palette does not apply to raw
input. A `continued` request resolves only an already published JSON artifact and
checks ID, byte length and SHA-256 before forward-only evolution.

The completed UI was inspected at 1440 px and 375 px. Four synchronized panes fit
without horizontal overflow; the IR view shows the hot running-F-16 exhaust,
cooler airframe/background and the separate IR viewpoint. There is no prior
committed four-pane visual baseline, so visual regression comparison is recorded
as inconclusive rather than a pixel-parity pass.

| Desktop | Mobile | IR preview only |
| --- | --- | --- |
| [Four-pane desktop](sf06/ir-capture-desktop.png) | [Single-column mobile](sf06/ir-capture-mobile.png) | [Thermal IR](sf06/ir-preview.png) |

## TDD evidence

Journeys were derived from SF-06 in `docs/BACKLOG.md`:

1. A simulator author can assign versioned thermal surfaces and off/idle/running
   heat states to imported equipment.
2. A capture client receives physically monotonic, calibrated raw LWIR that is
   independent of preview palette, RGB illumination and class IDs.
3. A replay client can save a thermal state, switch an engine off, reload the
   state and reproduce the same cooldown.
4. A lab user sees synchronized RGB/IR/reference panes whose raw artifacts obey
   calibration, shape, mask and publication contracts.

The pure-core RED checkpoint `3e43ad8` selected the new thermal suite and failed
with `ERR_MODULE_NOT_FOUND` for the intentionally absent `thermal.ts` (exit 1).
`f0427d8` made all six new analytical/replay guarantees GREEN. The capture RED
checkpoint `e01f468` changed API/browser expectations and failed because IR was
still advertised unavailable (1 failed, 8 passed; exit 1). `14b6536` made the
real worker/UI journey GREEN and is the final tested implementation.

| Guarantee | Test/evidence | Type | Result |
| --- | --- | --- | --- |
| Positive versioned materials and powered named regions | `thermal.test.ts`: catalog surfaces | integration | PASS |
| Equilibrium direction and 1 s versus 0.25 s stability | `thermal.test.ts`: simple surface | unit | PASS |
| Off < idle < running engine and hot exhaust/body separation | `thermal.test.ts`: equipment states | integration | PASS |
| Save/reload shutdown yields identical cooldown | `thermal.test.ts`: thermal state replay | unit | PASS |
| Planck response, emissivity and crossover are monotonic | `thermal.test.ts`: radiance | unit | PASS |
| Seeded noise repeats and palette cannot mutate raw | `thermal.test.ts`: detector/preview | unit | PASS |
| GPU pass publishes calibrated H x W raw/masks/state | `capture.spec.ts`: saved rig capture | browser E2E | PASS |
| Capture cancellation and browser closure remain safe | `capture.spec.ts` | browser E2E | PASS |
| Full legacy/streaming/aerodrome browser regressions | production Edge suite | browser E2E | PASS 16/16 |

Coverage command
`node --experimental-strip-types --experimental-test-coverage --test tests/sensors/*.test.ts`
passed 15/15 with 99.56% lines, 83.54% branches and 100% functions across the
loaded pure sensor core (`thermal.ts`: 99.24% lines / 75.00% branches; combined
branch coverage exceeds the required 80%). WebGL code is covered by the real
browser journey rather than claimed as Node coverage.

## Complete-cycle acceptance

| Gate | Exit | Result |
| --- | ---: | --- |
| `npm run verify` | 0 | Generated-contract drift/type checks; 64 contract, 19 world, 15 sensor, 4 asset and 81 backend tests; production build |
| Two independent `assets:import` runs | 0 / 0 | All seven outputs equal each other and committed bytes |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_GPU=1 PLAYWRIGHT_TEST_BUILT=1 npx playwright test` | 0 | 16/16 in 3.3 min on the production build |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_GPU=1 npm run capture:capabilities` | 0 | WebGL2, float readback, Chromium 153, RTX 3090 D3D11 |
| Three sequential GPU captures | 0 | Identical IR-radiance and thermal-state hashes |

The representative raw raster has 245,760 pixels: 150,417 valid (61.20%), five
saturated, and valid radiance 49.2817..200 W/(m2 sr), mean 49.9008. Running F-16
temperatures in the saved state are body 325.683 K, engine 412.945 K and exhaust
600.727 K. The off hidden F-16 exhaust is 314.798 K. These values prove fixture
separation, not real-vehicle calibration.

Representative raw artifacts:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| IR radiance NPY | 983,120 | `3f4f526ac87c92592d6d62040f696c363a6037c24ae38c041f387621c91541b4` |
| IR validity NPY | 245,840 | `9a62e90b2672168150f6d7be5fb6286983024832720defa49899f3478841b962` |
| IR saturation NPY | 245,840 | `019325cef85e9b9b9a3e40c638923c7dfac500d730c1bbad8ca0322ff81dd84d` |
| IR preview PNG | 58,207 | `a47a63079e0b2e5ea40fe342a8de276d4c853388d2e4bb0973088496e59d46de` |
| Thermal state JSON | 2,583 | `f51d4bd297bb4d98e03ed5254afeb0b8187c78b1c4b0266a26b3a8d5bc1b0c12` |

## Throughput and repeatability

Three RTX 3090 runs have end-to-end times 13.581 / 13.691 / 13.692 s and render
times 0.593 / 0.635 / 0.639 s. Median throughput is 4.38 captures/minute. Median
Node RSS is 127.1 MiB and browser heap is 147.7 MiB. The radiance and state hashes
are identical across all three runs. GPU allocation telemetry remains null, so
queue capacity stays one. Full samples are in
[capture-benchmark.json](sf06/capture-benchmark.json).

Two same-machine SwiftShader captures also repeat each other, but their float
raster hash differs from NVIDIA at edge pixels. Cross-device byte identity is not
claimed; pinned-renderer replay is the acceptance scope.

## Retained failures and limits

- The first Playwright invocation selected an absent bundled headless shell and
  never reached the app. Explicit local `msedge` rerun passed.
- The first IR browser assertion called rich `expect` once per pixel and consumed
  excessive test-runner CPU/memory after the worker had already succeeded. It was
  stopped and replaced with one linear scan plus aggregate assertions; the same
  real worker journey then passed.
- Physics are synthetic: no conduction between semantic nodes, angle-dependent
  emissivity, transmission, multiple reflection or sub-pixel mixture.
- SF-06 sets atmospheric transmission to one and path radiance to zero. Weather,
  hot-background presets and atmospheric LWIR effects remain SF-08.
- Terrain/buildings use ambient temperature and emissivity 0.95. The initial
  synchronized profile requires equal 640 x 384 RGB/IR dimensions.
- The fixed palette is display-only. Dataset publication/ObservationBundle
  assembly remains SF-10; SF-06 does not claim a training dataset.

