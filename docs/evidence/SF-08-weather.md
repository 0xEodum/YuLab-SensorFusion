# SF-08 weather, time and sensor noise acceptance

Date: 2026-09-24. Tested implementation revision:
`b95f729ed1d090467f97735a09afed622542135d` (pushed). Local acceptance
passed. The RED test checkpoint `1b5ca5a` (pushed) failed as expected with
`ERR_MODULE_NOT_FOUND` for the absent `packages/sensors/src/weather.ts`
(exit 1). The GREEN implementation adds the versioned profile in
[WEATHER.md](../WEATHER.md), UI controls, capture response, contract fields and
regressions.

## Verification

| Command | Exit | Result |
| --- | ---: | --- |
| `node --experimental-strip-types --test tests/sensors/weather.test.ts` before implementation | 1 | Missing weather module, expected RED |
| `npm run verify` | 0 | Contract drift check, type checks, 65 contract, 19 world, 29 sensor, 4 asset and 81 backend tests, production build |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_TEST_BUILT=1 YULAB_TEST_BACKEND_PORT=8875 npm run test:browser -- tests/browser/capture.spec.ts` | 0 | Existing synchronized capture, cancellation and browser-close cases, 3/3 |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_TEST_BUILT=1 YULAB_TEST_BACKEND_PORT=8877 npm run test:browser -- tests/browser/weather.spec.ts` | 0 | Rain capture, RGB-seed isolation, continued state and replay metadata, 1/1 |
| `git diff --check` | 0 | No whitespace errors |

The final [verify log](sf08/verify.log) has SHA-256
`192f805156b5d2149b1a42042d2691d65b854963e9b560b63b21b5dd7449fb85`;
the [weather browser log](sf08/browser-weather.log) has SHA-256
`b0d5641beda7180686ca2ed835904f27b6b4d86a2fb22ba3c3b3212364195730`.
The browser check ran on Windows, Node 25.6.1, Python 3.13.10, Edge Chromium
153.0.4234.48, ANGLE Vulkan SwiftShader. A representative full rain worker
job took 33.47 s; browser GPU allocation was unavailable.

## Fixed 30-seed sweeps

The fixtures use a fixed two-tone 32 x 32 RGB target at 90 m and a fixed
128-beam plane at 90 m. Each condition is paired by seed 0..29. The reported
intervals are normal-approximation 95% confidence intervals for the paired
mean difference:

| Controlled difference | Mean | 95% interval |
| --- | ---: | ---: |
| Clear minus fog RGB target/background contrast | 33.397 DN | 33.387..33.406 DN |
| Day minus night RGB contrast/noise SNR | 20.548 | 20.387..20.710 |
| Clear minus fog LiDAR surface returns (of 128 beams) | 78.367 | 75.710..81.024 |

Ideal LiDAR first-hit ranges were identical under clear/fog conditions. Rain
and snow produced 245 and 301 particle returns respectively over the 30 fixed
fixture seeds. The LWIR crossover fixture brought a 330 K object's
contrast down as the background approached its temperature while a 450 K
engine remained contrasted. The RGB fixture verifies seed replay and
weather-seed separation. These intervals describe simulator randomness on
the fixtures, not real-weather uncertainty. Short ranges, exposure changes,
cooler-than-background targets and near high-intensity LiDAR surfaces can
violate simple monotonic degradation; [WEATHER.md](../WEATHER.md) describes
those cases.

## Saved browser observations and replay

The first [rain request](sf08/rain-request.json) fixes aerodrome seed 0,
solar hour 12, severity 100%, tick 100 s, weather seed 11 and RGB/IR/LiDAR
seeds 0. Its [result](sf08/rain-result.json) records the frozen environment,
plan and calibration, plus all published artifact hashes. The raw
[RGB observation](sf08/rain-rgb.png), [LiDAR range preview](sf08/rain-lidar-range.png)
and [desktop capture](sf08/rain-desktop.png) were inspected. RGB shows seeded
precipitation speckles and distance attenuation; the range preview marks
particle and atmospheric-loss beams. Depth and instance references remain
geometric. In the 64 x 512 rain scan, beam statuses were 10,267 no return,
16,163 surface, 2,452 particle and 3,886 atmospheric dropout. IR calibration
records nonzero path extinction; raw IR remains separate from its preview.

The second [result](sf08/rgb-seed1-result.json) changes only the RGB seed from
0 to 1 at tick 100. The third [result](sf08/continued-result.json) uses the
second capture's hash-verified thermal-state artifact and advances to tick
101. At unchanged environmental equilibrium, the surface radiance is
expected to remain unchanged; the saved state and result tick advance.

| Artifact | RGB seed 0 SHA-256 | RGB seed 1 SHA-256 |
| --- | --- | --- |
| RGB PNG | `348f0b97b8934e088d29a9be4205a314b9a074cc30ac6fdf30187095c9a4dcda` | `24328815cad3027d1b46982236275f3648b18761734c59174b9b28af71cd6d94` |
| Depth NPY | `ddd4597405ae2d6528388f9921b2aa72ca3568a18498724a86f7a2e4b0b13e03` | same |
| Instance NPY | `aec86bd50ff1112b39d97c8301988ae8d4c4400b913cb3428a41310509b80f29` | same |
| IR radiance NPY | `a6afbb707d6dad18ffc24c1d64a574155ef7df5c55afda7f5e32263b1d6f1164` | same |
| LiDAR XYZ NPY | `8466ba2836fe135ca7ad5b01a6a9c1d2401074979b21fc919ef7d0c3f0be9f4b` | same |
| LiDAR beam-status NPY | `7bf1a06f74232f15e97a8d537b1a948fe1bc899b1810844a9d8f2f15815f16f8` | same |

The copied RGB PNG hash matches the published RGB artifact. The range
preview SHA-256 is
`d8cca95c14bc335a5fb74b56227542754bbfebd938b0988995409f1eb76451a3`;
the inspected desktop screenshot SHA-256 is
`710a989852c1aaaab8943a6f13a92722ab891a2650e0f401ef0954b6e045305f`.
Result/request JSON hashes are available from the committed files themselves;
the result JSON lists each underlying raw observation hash.

## Limits

Coefficients and particle rates are synthetic and not calibrated to measured
weather. RGB response runs on the renderer's tone-mapped 8-bit pass. LWIR
uses optical depth as a path-distance approximation. LiDAR beam time offsets
are metadata for a static synchronized scene; moving-scene timing remains
SF-13. Repeat hashes are scoped to this renderer/device. The 30-seed sweeps
are small deterministic fixtures; the browser check samples one rain scene.
