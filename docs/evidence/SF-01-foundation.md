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
