# SF-10 visibility labels and dataset jobs

The capture worker now publishes geometry-only RGB and IR instance-ID passes
from each saved camera pose. RGB depth/IDs exclude GLB surfaces declared
transparent by the importer; the IR pass follows its separate opaque-IR policy.
An isolated pass per instance measures its projected
silhouette. Visible masks are exact ID equality on the depth-tested pass, and
visible boxes are tight half-open rectangles around mask pixels. A target is
truncated when its raster intersects the frame and any posed mesh vertex lies
outside that camera's frustum. RGB noise, fog, darkness, and thermal crossover
do not change geometric labels. LiDAR ideal hits and surviving surface returns
are counted separately from their first-hit beam identities.

The per-frame `visible-pixels-16-lidar-3.v1` policy makes an object eligible at
16 visible pixels in either camera or 3 ideal LiDAR hits. Ineligible objects
retain `out_of_frustum`, `fully_occluded`, or `small_fragment` reason. A
LiDAR-only object with two hits is a small fragment; one with three is eligible.
3D boxes enclose the posed scene geometry, including independently rotated
turrets, in world-aligned coordinates. They remain amodal when occluded.

`tools/generate-sf10-requests.ts` creates up to 300 deterministic tri-modal
requests over six site/seed groups, five views and ten conditions. Group IDs are
site plus layout seed; four groups train, one validates and one tests. The
request manifest contains observation inputs and generator settings; it does
not contain labels. The default throughput pilot uses 320 x 192 RGB/IR and
32 x 256 LiDAR beams. Resolution and sample count can be changed with the
script's flags. The 640 x 384 / 64 x 512 profile in DATA_CONTRACTS.md remains
the larger pilot proposal for the learning stage.

```powershell
node --experimental-strip-types tools/generate-sf10-requests.ts --output artifacts/sf10/requests.json --count 300
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_GPU='1'
backend\.venv\Scripts\python.exe tools\dataset-job.py --requests artifacts\sf10\requests.json --output artifacts\sf10\pilot --count 300
backend\.venv\Scripts\python.exe tools\dataset-job.py --requests artifacts\sf10\requests.json --output artifacts\sf10\pilot --validate
```

The job state is durable in `job-state.json`; `--resume` rechecks already
published captures before continuing. `--cancel` writes a cancellation request
that is honored before the next capture. Worker output is published by renaming
its complete `.partial` directory. Each dataset capture is likewise packaged
in a `.partial` directory and renamed only after bundle and raw-file readback.
The manifest is published last. A failed, cancelled or interrupted job has no
complete manifest. Restart removes only checked paths inside its designated
partial roots.

Each capture directory contains `observation.json`, `annotations.json`, and
`truth.json` plus content-hashed raw arrays and per-object Boolean masks.
Observation input reads only `observation.json` and its referenced raw sensor
arrays; it accepts only `capture_id` and rejects any extra truth-bearing fields.
Truth and annotation files can be absent without affecting this read boundary.
`manifest.json` records an inventory hash for every capture file, provenance,
class map and group splits. The validator checks payload versions, the complete
file inventory, every published raw hash, referenced
array shapes, bundle identities, duplicate tri-modal observations, group
disjointness and split counts. The builder also compares raw shapes, dtypes,
finite values and saved calibration against the request before publication.

The policy and image geometry are checked by 24 independently specified raster
fixtures; the dataset tests additionally cover duplicate IDs, interrupted
publication, version mismatch, split leakage and unknown truth request fields.
