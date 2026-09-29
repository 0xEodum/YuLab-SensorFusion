# SF-10 visibility and dataset acceptance

Date: 2026-09-29. Frozen pilot source revision:
`fa50c39167a2956996a5298709e888eca0e50c62`.
Request manifest SHA-256:
`b189a72bd4524344bf8cf905aeea6b33465bcd7abeff80a86a4037f8d28ab010`.
The capture environment is Windows with Playwright's `msedge` channel and
`PLAYWRIGHT_GPU=1`. The 24-fixture source file
`backend/tests/test_dataset.py` has SHA-256
`e772cd1e2614c7f505b377241653d18d40d07e02f68d0946d4b801ae1f92dc25`.

The request generator produced 300 tri-modal captures over six independent
layout groups: `airfield-0`, `airfield-48291`, `harbor-7` and `harbor-90210`
in train, `airfield-2718` in validation, and `harbor-31415` in test. Each
group has 50 captures (five camera poses by ten conditions). All 300 request
snapshot hashes match independently recomputed canonical SHA-256 values; all
capture IDs are distinct. The pilot uses 320 x 192 RGB/IR and 32 x 256 LiDAR.

## Local checks

| Check | Result |
| --- | --- |
| `npm run verify` after complete file inventory | Pass: 65 contract, 20 world, 30 sensor, 8 asset, 108 backend tests; production build |
| Frozen visibility fixtures | 24 explicit rasters with expected masks, half-open boxes, fractions and eligibility |
| `tools/qa-sf10.py` on a complete one-capture dataset | Pass: 11 observation arrays loaded without truth/annotation files; deliberate RGB corruption rejected |
| Browser capture regression after separate RGB/IR passes | Pass on Edge; RGB label pass matched frozen RGB reference IDs exactly |
| Harbor RGB opacity correction | Transparent imported planes excluded from RGB depth/ID labels; matched ship mask shrank from 3,067 to 2,447 pixels, with no rectangle over the mast |
| Harbor nonresident objects | Direct worker capture of ship-side and both truck-side viewpoints packaged successfully; the ship-side view retained off-range trucks in truth with zero camera pixels. `tests/browser/sf09.spec.ts` passed on Edge after one transient backend fetch failure. |

I inspected the [airfield label overlay](sf10/visibility-overlay.png),
[harbor label overlay](sf10/harbor-visibility.png),
[RQ-4 correction](sf10/rq4-corrections.png),
[SPAA turret](sf10/spaa-turret.png),
[airfield buildings](sf10/airfield-buildings.png) and
[harbor road](sf10/harbor-road.png). The harbor cruiser mask tracks its visible
silhouette around the mast and bow; the other ship is partly occluded by the
quay from its own camera viewpoint. RQ-4 gear and intake geometry, turret yaw,
the revised buildings and non-airfield truck placement are visible in the
linked views.

The parallel asset/world changes add deterministic off, idle and running
states per parked vehicle, with engine heat following that state. Imported
SPAA turrets receive seeded yaw about their actual pivot. The RQ-4 import now
uses a vertical engine rim and gear connected to its fuselage. Airfield and
quay buildings have additional structural detail, and the harbor layout has
ground vehicles on the quay road.

In the published `sf10v4-0130` harbor capture, quay truck 3 has 648 RGB pixels,
640 IR pixels and 115 ideal LiDAR hits and is eligible. Quay truck 4 remains
in truth with zero current-frame pixels/hits and `out_of_frustum` status.

## 300 capture readback

The single-worker job completed with `state=succeeded`, zero reused captures
and exit code 0. The published `artifacts/sf10/pilot-300-v4/manifest.json`
has SHA-256
`c71680f7e2d2451991a772a05c6b977a8944c476cd453d1dcf1b9f0bace47ebe`.
The job took 5,076.44 seconds (0.0591 captures/s or 3.55/min), published
720,572,553 bytes (2,401,908.51 bytes/capture), and estimates 7,205,725,530
bytes for 3,000 captures at this profile. The split counts are 200 train,
50 validation and 50 test.

```powershell
backend\.venv\Scripts\python.exe tools\dataset-job.py --requests artifacts\sf10\requests-v4.json --output artifacts\sf10\pilot-300-v4 --validate
backend\.venv\Scripts\python.exe tools\audit-sf10-pilot.py artifacts\sf10\pilot-300-v4 artifacts\sf10\requests-v4.json --output docs\evidence\sf10\pilot-audit.json
```

Both commands exited 0. The validator checked all 300 capture inventories,
file hashes, array metadata, bundle references, versions, duplicates and group
splits. The [independent audit](sf10/pilot-audit.json) recomputed every mask,
tight half-open box, visible fraction, LiDAR hit count and eligibility decision
from the raw identity arrays; it also checked calibrations and request snapshot
hashes. Its SHA-256 is
`c37e93b6cea8b15a0eb3cd4438e2d144deacd9e18005e2370cb2c0abb295c5c7`.

The 1,500 object records comprise 600 aircraft, 600 ground vehicles and
300 ships. There are 510 eligible records and 990 ignored as out of frustum.
RGB and IR each have 180 partly visible records and 190 truncated records.
All 30 ten-condition sequences have identical RGB, IR and ideal LiDAR geometry
identity hashes across their variants.
No layout group crosses a split.

Limits: this throughput pilot uses 320 x 192 RGB/IR and 32 x 256 LiDAR, below
the proposed SF-11 learning profile. Fully occluded and tiny-fragment policies
pass frozen fixtures but did not arise among the 300 pilot records; all ignored
pilot records were out of frustum. The observation-only loader was verified
with truth and annotation files unavailable, while actual model inference is
part of SF-11 and later tasks.
