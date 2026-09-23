# SF-07 first-return LiDAR acceptance

Date: 2026-09-23. Tested implementation:
`a8587eb5ab57bdc0da4c2df656914478de9d5d2f`. Local acceptance passed.
The [verification manifest](sf07-verification-manifest.json) records exact
commands, source identity, fixture outcomes, raw artifact hashes and limits.
This evidence commit refers to the prior tested implementation revision.

## Delivered

The saved rig now emits a separate 64 x 512 LiDAR pattern in the +X forward,
+Y left, +Z up sensor frame. Each beam has an explicit angular direction,
row-major ID and time offset. The worker unions RGB and LiDAR sensor residency,
then casts beams into the same terrain, decoration, aerodrome and catalog
triangles used by the optical capture. Per-mesh triangle BVHs and a scene-mesh
BVH accelerate the nearest intersection. Catalog `opaque_lidar` flags and the
declared two-sided solid/face policy apply before seeded receiver response.

Completed jobs publish sparse float32 sensor-frame XYZ/intensity/time, uint32
beam IDs, a validity array, a full no-return/status table, ideal range and
instance truth, calibration metadata and separate range/point-cloud previews.
The backend publishes them atomically with the RGB/IR/reference artifacts and
advertises LiDAR only when the capture worker capability probe succeeds.

| Desktop | Mobile | LiDAR previews |
| --- | --- | --- |
| [Six-pane desktop](sf07/capture-desktop.png) | [Single-column mobile](sf07/capture-mobile.png) | [Range](sf07/lidar-range.png) / [point cloud](sf07/lidar-cloud.png) |

The desktop and 375 px mobile captures were inspected. The range image shows
the surface boundary and distant scene; the top-down point plot retains sparse
terrain arcs and returns near the aircraft. The point plot is not an RGB camera
projection. No committed six-pane baseline exists, so pixel-regression
comparison is inconclusive. The raw arrays, not these PNGs, are sensor input.

## Acceptance results

The RED checkpoint `f9bf414` added the first-return tests and failed with
`ERR_MODULE_NOT_FOUND` for the absent `lidar.ts` (exit 1). The GREEN
implementation is `a8587eb`. The `tests/sensors/lidar.test.ts` fixtures now
pass the following:

| Requirement | Result |
| --- | --- |
| Wall before target, wall removal, receiver dropout | Only front wall wins; dropout yields no point and never exposes the target |
| Partial occlusion and arch opening | Beams through the opening reach the target; lintel/pier beams stop at the front geometry |
| Thin and grazing faces, inside/outside | Two-sided thin surface and solid exit face return; grazing response stays finite and weak |
| Range, seam, ties, empty scan | Min/max rejects out-of-range hits; both sides of an x=0 chunk seam hit; ties repeat; empty scan has only no-return statuses |
| Acceleration and calibration | Fixed accelerated rays match brute-force Three.js raycast within 1 mm away from ties; co-located central ray projects within 0.5 RGB pixel |
| Material opacity | A declared `opaque_lidar=false` catalog surface is excluded |

`npm run verify` passed (exit 0): 64 contract, 19 world, 23 sensor, 4 asset and
81 backend tests, generated-contract drift check, TypeScript type checks and
production build. The production-built local Edge suite passed 16/16 (exit 0),
including capture publication, cancellation, browser closure, raw LiDAR array
shape/finite checks, visible-instance support and hidden-instance absence.
The added final browser assertion also passed in a focused 1/1 rerun. Logs are
[verify](sf07/verify.log), [production browser](sf07/browser-production.log)
and [focused capture](sf07/browser-capture-final.log).

The representative 64 x 512 clear-scene capture contained 20,627 surface
returns and 12,141 no-return beams, with zero receiver dropouts. All XYZ were
finite; every status-1 beam had exactly one sparse point. Ideal instance
counts were 445 for the visible F-16 and 56 for the wider aircraft; the
fully hidden fixture had zero hits. The [capture metadata](sf07/capture-metadata.json)
lists each artifact's byte length and SHA-256. Three independent same-machine
Edge/RTX captures of the same rig and seed had identical LiDAR XYZ hash
`508f213d9be7b098bddf46149fe7a6f101e7d9902a217048d908456dfc97014d`
and beam-status hash
`82bcaea544e3d39d0d3f8cc3546b88bb22a3f599596c82f391d1d497a565c79c`.
Median worker latency was 13.41 s; median browser render/scan time was 1.09 s.
These figures are scoped to Windows, Edge Chromium 153, ANGLE Direct3D11 and
an RTX 3090. GPU allocation telemetry is unavailable; the queue remains one.

## Limits and resolved failures

The response coefficients are synthetic and uncalibrated; weather/atmospheric
returns remain SF-08. The scene is frozen at one tick despite declared beam
times; moving-scene interpolation remains SF-13. Repeat hashes establish
determinism only for this pinned renderer and machine, not cross-device bytes.

Initial browser captures timed out after writing artifacts because the larger
result JSON filled a Windows subprocess stdout pipe while the parent waited
for exit. The backend now drains into temporary files during execution. A
separate browser check found nonfinite XYZ from a signed hash conversion in
the seeded noise generator; it now converts to unsigned before normalization.
Thirty seeded fixture scans and real raw-array checks pass. A final calibration
review corrected the horizontal beam-order sign so column zero is sensor-left,
matching the metadata and preview.
