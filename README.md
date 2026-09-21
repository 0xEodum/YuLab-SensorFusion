# YuLab Sensor Fusion

A procedural terrain editor being developed into an RGB, thermal IR and LiDAR
simulation and detection lab. SF-01 adds a frontend workspace, local backend,
shared contracts and verification. SF-02/SF-02R add a connected deterministic
world, seeded regional formations, and a nine-chunk preview. Sensor capture,
datasets, training and inference are
later stages; no trained model is supplied yet.

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
`http://127.0.0.1:8000/docs`. Health and capabilities are the only implemented
operations. The editor shows connected, unavailable and incompatible-response
states; terrain editing and exports also work with the backend stopped.

Choose **Explore the connected world** above the editor (or open `?view=world`)
to view connected 128 m chunks within a 2,048 × 2,048 m world. Seed zero works;
region and camera selectors inspect arches, tunnels, outcrops and chunk seams.
The preview loads nine fixed chunks around any of 16 seeded regions and renders
regional/local relief, low-poly formations, deterministic trees and rocks.
Landscape and landmark-detail cameras support overview and close inspection.
Streaming and free navigation remain SF-03.
See the [world generator profile](docs/WORLD_GENERATOR.md) for coordinates,
mesh tolerances, supported features and reproducibility limits.

`npm run build` writes `frontend/dist/`; `npm run preview` serves that build and
proxies `/api` in the same way. The current single-file HTML remains an editor
export, not a self-contained backend. For another backend port, set
`YULAB_BACKEND_PORT` for Vite and launch uvicorn on that same port. Remote hosts
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

To run that same browser suite against the production build, run `npm run build`
and set `$env:PLAYWRIGHT_TEST_BUILT='1'` before `npm run test:browser` (POSIX:
`PLAYWRIGHT_TEST_BUILT=1 npm run test:browser`). Both modes require a fresh
isolated server; they never reuse an unrelated process already on port 4173.

`verify:world` checks all 256 chunks and all 480 seams for seeds 0 and 48291,
including shuffled request order, triangle topology and surface coverage.

Individual commands: `npm run typecheck`, `npm run test:world`, `npm run test:contracts`,
`npm run test:backend`, `npm run contracts:generate`, `npm run contracts:check`.
Changing generated code directly fails the drift check. See
[contract ownership and validation](contracts/README.md).

## Repository

- `frontend/`: existing React/Three.js editor and backend connection status.
- `backend/`: isolated Python API, generated types and tests.
- `contracts/`: canonical JSON Schema/OpenAPI and shared positive/negative fixtures.
- `packages/contracts/`: generated TypeScript bindings and runtime validation.
- `packages/world/`: deterministic fields, chunk meshes, placements and legacy adapter.
- `tests/`, `tools/`: browser/contract checks and repeatable tooling.
- `docs/`: [architecture](docs/ARCHITECTURE.md), [backlog](docs/BACKLOG.md),
  [data semantics](docs/DATA_CONTRACTS.md), [ESSRF design](docs/ESSRF.md), and
  [SF-01 evidence](docs/evidence/SF-01-foundation.md) and
  [SF-02 evidence](docs/evidence/SF-02-connected-world.md) plus its
  [SF-02R quality correction](docs/evidence/SF-02R-procedural-quality.md).

Datasets, imported asset bundles, caches and model checkpoints belong under
ignored `artifacts/`/`assets/imported/`, not ordinary Git history. Versioned
manifests identify them when their implementation stages are reached.
