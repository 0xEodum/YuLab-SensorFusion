# YuLab Sensor Fusion

A procedural terrain editor being developed into an RGB, thermal IR and LiDAR
simulation and detection lab. SF-01 adds a frontend workspace, local backend,
shared contracts and verification. SF-02/SF-02R add a connected deterministic
world and seeded regional formations. SF-03 adds worker-backed chunk streaming,
free flight, browser-persisted rig poses, display LOD and independent sensor
geometry readiness. SF-04 adds the initial metre-scale model catalog/aerodrome;
SF-05 through SF-07 add backend-owned synchronized RGB, reference, raw thermal
IR and sparse first-return LiDAR capture. See [streaming controls and limits](docs/STREAMING.md).
Local datasets, training and checkpoint inference are implemented. The accepted
static sensor ensemble achieves fresh-holdout clean mAP .797 and degradation
macro .771; see [quality results and inference](docs/evidence/SF-Q-quality.md).
Checkpoints and datasets remain local artifacts outside Git. Training/inference
service and UI integration remain later stages.

## Setup

Use Node 22 LTS (at least 22.12), npm, and Python 3.13. Verification runs locally;
the recorded Windows environment also uses Node 25. The npm lock and
`backend/uv.lock` pin dependencies. Python uses `backend/.venv`, not global ML
packages. No external model directory or GPU is needed for SF-01.

```powershell
npm ci
python -m venv .tools
.\.tools\Scripts\python.exe -m pip install uv==0.12.17
npm run backend:sync
```

On Linux/macOS, bootstrap uv with `.tools/bin/python -m pip install uv==0.12.17`.
An existing uv 0.12.17 on PATH also works. Root helper commands prefer the local
`.tools` installation when present. Do not install the backend into global Python.

## Run

Start these in two terminals at the repository root:

```powershell
npm run dev:backend
```

```powershell
npm run dev
```

Vite prints the frontend URL (normally `http://127.0.0.1:5173`). The backend binds
to `127.0.0.1:8000`; Vite proxies `/api` to it. Backend API documentation is at
`http://127.0.0.1:8000/docs`. Health/capabilities plus capture submission,
polling, cancellation and artifact reads are implemented. The editor shows connected, unavailable and incompatible-response
states; terrain editing and exports also work with the backend stopped.

Choose **Explore the connected world** above the editor (or open `?view=world`)
to view connected 128 m chunks within a 2,048 × 2,048 m world. Seed zero works;
region and camera selectors inspect arches, tunnels, outcrops and chunk seams.
The preview loads nine fixed chunks around any of 16 seeded regions and renders
regional/local relief, low-poly formations, deterministic trees and rocks.
Landscape and landmark-detail cameras support overview and close inspection.
SF-03 streams the surrounding chunks as you orbit/pan or fly; use the Navigation
and Display detail controls, and Save rig pose to bookmark the current view.
See the [world generator profile](docs/WORLD_GENERATOR.md) for coordinates,
mesh tolerances, supported features and reproducibility limits.

On the aerodrome, save a rig and choose **Capture RGB, IR, LiDAR and references**.
The six panes share one capture ID/tick; raw IR radiance, masks, replayable thermal
state and sparse LiDAR arrays remain downloadable job artifacts. The palettes
are preview-only. See the [thermal/IR profile](docs/THERMAL_IR.md),
[LiDAR profile](docs/LIDAR.md) and [capture contract](docs/CAPTURE.md).
Local LiDAR acceptance and raw artifact identities are recorded in
[SF-07 evidence](docs/evidence/SF-07-lidar.md).

`npm run build` writes `frontend/dist/`; `npm run preview` serves that build and
proxies `/api` in the same way. The current single-file HTML remains an editor
export, not a self-contained backend.
The world worker is a separate generated JavaScript asset: serve/copy the whole
`frontend/dist/` directory for the explorer. Set `YULAB_BACKEND_PORT` for Vite
and launch uvicorn on that same port. Remote hosts
are not accepted by the proxy configuration.

## Verify

```powershell
npm run verify
npm run verify:world
npx playwright install chromium
npm run test:browser
```

`verify` checks generated-file drift, all workspace/test TypeScript, shared wire
fixtures in JavaScript and Python, world geometry contracts, API responses/errors and the production
build. Browser tests start an isolated backend on port 8765 and Vite on 4173.
Those ports must be free. GitHub workflows are removed by project policy; run
both core and browser checks locally before pushing. Local Windows Edge passed
the full browser suite. For a local download
failure, explicitly select installed Edge with `$env:PLAYWRIGHT_CHANNEL='msedge'`
(POSIX: `PLAYWRIGHT_CHANNEL=msedge npm run test:browser`). Browser tests use
software WebGL for portable functional QA; they are not GPU benchmarks.

For the SF-03 104-boundary traversal performance gate, set
`$env:PLAYWRIGHT_GPU='1'`. The report records the actual renderer, 1280 × 720
canvas, frame/generation p50/p95, bounded cache/resource counts and forced-GC
heap samples under `artifacts/sf03/`. Hardware runs enforce median >=30 fps and
p95 <=50 ms. Software compatibility runs report latency without that GPU gate.

To run that same browser suite against the production build, run `npm run build`
and set `$env:PLAYWRIGHT_TEST_BUILT='1'` before `npm run test:browser` (POSIX:
`PLAYWRIGHT_TEST_BUILT=1 npm run test:browser`). Both modes require a fresh
isolated server; they never reuse an unrelated process already on port 4173.

`verify:world` checks all 256 chunks and all 480 seams for seeds 0 and 48291,
including shuffled request order, triangle topology and surface coverage.
Pass `-- --aerodrome` to verify the graded airfield profile and write its reports
under `artifacts/sf04/`.

Individual commands: `npm run typecheck`, `npm run test:world`, `npm run test:contracts`,
`npm run test:backend`, `npm run contracts:generate`, `npm run contracts:check`.
Changing generated code directly fails the drift check. See
[contract ownership and validation](contracts/README.md).

## First aerodrome and models

Open the connected world and select **Open aerodrome**, or visit
`/?view=world&site=aerodrome`. Inspect F-16, RQ-4 and the 8×8 vehicle from the
catalog cards. They share metre scale and retain source proportions. Visibility
fixtures demonstrate open, partial and closed-hangar views. The bundled GLBs
and metadata work without the original model projects.

Reimport with `npm run assets:import -- "K:\PycharmProjects\world_models\Generated"`.
An optional second path writes a comparison bundle. `npm run test:assets` checks
hashes, mesh normals, scale, contacts, clearances and graded seams. See
[asset/airfield documentation](docs/ASSETS_AND_AERODROME.md) for scope and limits.

## Repository

- `frontend/`: existing React/Three.js editor and backend connection status.
- `backend/`: isolated Python API, generated types and tests.
- `contracts/`: canonical JSON Schema/OpenAPI and shared positive/negative fixtures.
- `packages/contracts/`: generated TypeScript bindings and runtime validation.
- `packages/world/`: deterministic fields, chunk meshes, placements and legacy adapter.
- `packages/assets/`: validated catalog, shared templates and aerodrome scene geometry.
- `frontend/public/catalog/`: self-contained three-model runtime bundle and source provenance.
- `tests/`, `tools/`: browser/contract checks and repeatable tooling.
- `docs/`: [architecture](docs/ARCHITECTURE.md), [backlog](docs/BACKLOG.md),
  [data semantics](docs/DATA_CONTRACTS.md), [ESSRF design](docs/ESSRF.md), and
  [SF-01 evidence](docs/evidence/SF-01-foundation.md) and
  [SF-02 evidence](docs/evidence/SF-02-connected-world.md) plus its
  [SF-02R quality correction](docs/evidence/SF-02R-procedural-quality.md), and
  [SF-03 streaming acceptance](docs/evidence/SF-03-streaming-navigation.md), and
  [SF-04 assets and aerodrome](docs/evidence/SF-04-assets-aerodrome.md), and
  [SF-05 calibrated capture acceptance](docs/evidence/SF-05-capture-worker.md), and
  [SF-06 thermal IR acceptance](docs/evidence/SF-06-thermal-ir.md).

SF-05/SF-06 capture worker details and raw reference/IR formats are documented in
[docs/CAPTURE.md](docs/CAPTURE.md). With a local Chromium channel available:

```powershell
$env:PLAYWRIGHT_CHANNEL='msedge'
npm run capture:capabilities
```

Datasets, larger future asset bundles, caches and model checkpoints belong under
ignored `artifacts/`/`assets/imported/`, not ordinary Git history. Versioned
manifests identify them when their implementation stages are reached.

SF-11 local collection/training/checkpoint inference commands, the separate
hash-locked PyTorch environment, and exact preprocessing/evaluation semantics
are documented in [the learning baseline profile](docs/LEARNING_BASELINES.md).
