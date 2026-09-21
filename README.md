# YuLab Sensor Fusion

A procedural terrain editor being developed into a reproducible RGB, thermal IR,
and LiDAR simulation and detection lab.

**Current status:** architecture and implementation planning only. The application
still runs the original terrain editor. Sensors, datasets, the backend, and a
trained detector are not implemented yet.

## Run the existing editor

```powershell
npm ci
npm run dev
```

Existing verification commands:

```powershell
npm run build
npx tsc --noEmit
```

## Implementation documents

- [Architecture and decisions](docs/ARCHITECTURE.md): boundaries, world generation,
  assets, sensors, storage, services, and demonstration.
- [Data and sensor contracts](docs/DATA_CONTRACTS.md): units, visibility, observation
  payloads, provenance, and access boundaries.
- [Implementation backlog](docs/BACKLOG.md): ordered tasks, dependencies, acceptance
  gates, and commit/push checkpoints. Start with `SF-01`.
- [ESSRF design](docs/ESSRF.md): research architecture and explicitly scoped lab
  implementation profiles. Architectural claims are not measured model results.

Large generated datasets, imported build artifacts, and training checkpoints will
be stored outside ordinary Git history; versioned manifests will identify them.
The external model library is an import source, not a runtime dependency.
