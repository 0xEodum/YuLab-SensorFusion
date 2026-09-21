# SF-01 verification

## Checkpoint A: frontend workspace

Baseline: `68c57878ece2026fe5e77667d3a9982de873ffa5`.
The six original `src/` files moved into `frontend/src/` without content changes;
[normalized source hashes](sf01-move-identity.json) record the comparison.
Root npm commands delegate to the frontend workspace. Vite was patched from
7.3.2 to 7.3.6 and esbuild's compatible patch updated after npm audit identified
Windows development-server advisories. No terrain logic or dependency major
version was changed.

Checks on Windows / Node 25.6.1 / npm 11.9.0:

| Command | Exit | Result |
| --- | --- | --- |
| `npm run build` | 0 | Frontend production build |
| `npm run typecheck` | 0 | Frontend TypeScript |
| `npm audit fix` | 0 | Compatible lock update; zero reported vulnerabilities |
| `$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:browser` | 0 | 2 browser tests passed |

Browser tests exercised all four presets, seed changes, drag orbit, zoom, top
view/reset and real PNG/OBJ/GLB downloads with binary/header checks. Narrow-screen
layout and help dialog passed. Desktop screenshot visually inspected. The first
mobile test used hidden text as a selector; changing it to the existing guide
button fixed the test without changing the editor. Local pinned Chromium download
timed out; the explicit Edge channel fallback was used with software WebGL.
This is functional browser QA, not a GPU performance benchmark or a pixel
regression claim. No prior image baseline was available.

Local browser artifacts: `artifacts/browser/` (ignored). SF-01 remains IN PROGRESS
until the backend, generated contracts, negative fixtures and CI pass.

## Checkpoint B: contracts, backend and connection UI

Checkpoint A source: `57060ca`. Canonical JSON Schema contains 13 payload
families (ten lab families and three API envelopes), with generated TypeScript
and Python bindings and a bundled OpenAPI document. Only health and capability
operations are implemented. Backend responses are validated against the same
schema consumed by the frontend; all planned lab capabilities report unavailable.

Local checks before committing checkpoint B:

| Command | Exit | Result |
| --- | --- | --- |
| `npm run backend:sync` | 0 | Isolated Python 3.13 environment from uv lock |
| `npm run verify` | 0 | Drift check, TypeScript, 62 JS checks, 72 Python checks, production build |
| `$env:PLAYWRIGHT_CHANNEL='msedge'; npm run test:browser` | 0 | 5 browser tests, including live backend through Vite |
| `uv lock --project backend --check` | 0 | Lock agrees with project metadata |
| `git diff --check` | 0 | Patch whitespace check |

Local browser: Edge 153.0.4234.32 via Playwright 1.63.0, software WebGL. Desktop
and mobile screenshots visually inspected. Tests cover connection interruption,
retry recovery and incompatible response rejection, plus the original editor
journey. Interruption is injected at the browser network boundary; the connected
case calls the actual backend through the actual Vite proxy.

Test-first evidence: API tests initially failed because `app.main` was absent.
After provider implementation, the shared bad-timestamp case exposed a missing
Python RFC3339 format dependency; adding the pinned validator resolved parity.
The TS generator initially interpreted 2020-12 tuples as `never[]`; a local
tuple-syntax adaptation and compile-time matrix checks now prevent that drift.

Two upstream test-client deprecation warnings and a code-generator formatter
future warning remain; all checks pass. SF-01 validates wire metadata, not
physical sensor behavior or binary artifact contents. Final clean-checkout and
CI results are recorded below when available.
