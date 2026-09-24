# SF-09 catalog and harbor acceptance

Date: 2026-09-24. Tested and pushed implementation revision:
`dc967b1e118706ee11947ea92624b1f55fcde22b` (parent
`7a555021ad1bcc24f50f8773f7bd7dd7636ff6e1`). Local acceptance passed
for the user-approved **15 complete projects**. Source revision is
content-addressed: each catalog record has a `source.sha256` over its ordered
source-file hashes, and its sidecar lists those files. The supplied source
tree is external to this repository.

The original 17-project set is accounted for. `aircraft/b-52-model` has
`src/components/Scene.tsx` importing a missing `./Aircraft` component.
`aircraft/mirage-2000-model` has geometry helpers but only a placeholder
`src/App.tsx`, without an assembled aircraft. The user explicitly revised
SF-09 to the 15 usable projects; these two have no substitute catalog entries.
The [catalog and harbor notes](../HARBOR_AND_CATALOG.md) map every imported
project to its asset ID and measured authored dimensions.

## Local verification

| Command/check | Exit | Observed result |
| --- | ---: | --- |
| `npm run assets:import -- K:\PycharmProjects\world_models\Generated` | 0 | 15 records, 15 GLBs and 15 sidecars |
| Reimport to `artifacts/sf09/import-repeat` and compare SHA-256 | 0 | All 31 catalog files byte-identical |
| `npm run verify:world -- --harbor` | 0 | Seeds 0 and 48291: 256 chunks, 480 matching seams and 262,144 finite surface probes each; shuffled replay matched every geometry and placement hash |
| `npm run verify` | 0 | Contract generation, type checks, 65 contract, 20 world, 30 sensor, 6 asset and 81 backend tests; production build |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_GPU=1 YULAB_TEST_BACKEND_PORT=8766 npm run test:browser` | 0 | Existing 17 browser regressions passed on Edge, including capture, streaming and weather |
| `PLAYWRIGHT_CHANNEL=msedge PLAYWRIGHT_GPU=1 PLAYWRIGHT_TEST_BUILT=1 YULAB_TEST_BACKEND_PORT=8767 npx playwright test tests/browser/sf09.spec.ts` | 0 | Production harbor capture: cruiser instance pixels, both ships' thermal nodes and all seven synchronized panes |
| Same production configuration, backend port 8768, `npx playwright test tests/browser/assets.spec.ts` | 0 | Existing catalog and failure behavior, 2/2 |
| `node tools/qa-sf09.mjs` | 0 | Seven matched-scale browser views, eight target visibility probes, harbor sensor scene and two distinct seeded camera viewpoints; no page/HTTP errors |
| `git diff --cached --check` | 0 | No whitespace errors |

The [seed-0 report](sf09/world-verification-0.json) has SHA-256
`120d787d1c0179e8d01540e40c41e4859575e0f150c6555a7c2cbf40a5c07fcc`
and 2,422,854 terrain triangles. The [seed-48291 report](sf09/world-verification-48291.json)
has SHA-256 `ab52df15edc5b15dd339a4e4387dad44b79bc21ea8da79d6eb75690cae2880b5`
and 2,368,044 triangles. Their world-spec SHA-256 values are
`fcf78f7e86b84e672eaaede4d103053b53b76c1e7c0b133ff2fa76bc2972dcba`
and `a6cead05be5270ce2e7dc2178a1eedf063932a04c302d3577e19849bd199d1c9`.
The catalog JSON SHA-256 is
`89f4121c6ba964b85a637bf3d4bdc4860e681d35a8dd7349991691e18137b762`.

## Visual and sensor observations

The [browser acceptance record](sf09/acceptance.json) has SHA-256
`823e10049acfd120805e7309ac3b6ac3044eb24997867b7d71e0c3e243874d40`.
It was replayed against the pushed implementation revision: the JSON and all
seven view screenshots matched byte for byte. At seed 0, the harbor loaded two
ship templates and instances; the mixed airfield loaded six; the empty harbor
loaded zero. Both ships were present in the independent 2 m sensor residency
with piers and water. The cruiser had 217/237 projected triangle probes
visible (0.916); the destroyer had 234/261 (0.897). All six mixed-airfield
instances had nonzero probes and a visibility fraction of 1.0 from their
inspection poses. The 15-asset unit fixture also checked one real GLB triangle
per asset as a first return, then verified that a closer triangle occludes it.
Thermal equilibrium increased monotonically from off to idle to running on
each asset's powered exterior region.

I inspected [the harbor overview](sf09/harbor-oblique.png),
[dockside view](sf09/harbor-ground.png), [ship detail](sf09/harbor-detail.png),
[mixed airfield](sf09/airfield-mix.png) and [empty harbor](sf09/harbor-empty.png)
at the same browser viewport and canvas scale. The overview clearly shows
both 180 m class ships beside the quay, with piers, cranes, stacked containers,
water extending into atmospheric distance and grounded airfield aircraft on
marked stands in the corresponding airfield frame. The dockside view shows
the cruiser at water level. The empty harbor retains the site geometry without
ships. The production [harbor capture view](sf09/harbor-capture-view.png)
has SHA-256 `d4443aac410c67d5b8d98cf9e3abf87a5502e9dcb31b7aeeb99ef2bede2539fe`.

Environment: Windows, Node 25.6.1, Python 3.13.10, Edge Chromium
153.0.4234.48. The browser suite used the `PLAYWRIGHT_GPU=1` launch path;
hardware GPU identity was not established. Import byte identity and rendered
pixel hashes are scoped to this local toolchain and renderer.

## Limits

The models are source-authored low-poly representations at a shared metre
scale, not certified physical dimensions. Thermal properties, sea level and
water appearance are synthetic; water has small static waves and no buoyancy
or wake simulation. The F-22 source has no landing gear, so its imported model
is catalog-only and is not placed on grounded airfield stands. The static
adapters omit source-app controls, projectiles and line helpers. The two
incomplete source projects remain outside the revised 15-project scope.
Visibility probes and the one production harbor capture verify this local
scene and renderer; dataset label generation and training remain SF-10 onward.
