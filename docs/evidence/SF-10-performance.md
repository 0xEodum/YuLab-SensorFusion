# SF-10 collection performance follow-up

Date: 2026-09-30. Sensor/session implementation: `b0935f0`.
Final implementation including strict result validation: `99131c8`.
SF-11 remains READY; no learning/model milestone was advanced.

## Cause and change

The original coordinator launched Node, bundled the browser code, started an
asset server and browser, and generated every fixed-2-m terrain chunk for every
packet. Meshing ran synchronously on one JavaScript thread before rendering.
In the instrumented 24-request baseline, mean terrain meshing was 14,086.99 ms;
mean RGB/reference, visibility, thermal, LiDAR build/scan/preview together was
992.52 ms. The GPU spent most of the packet waiting for CPU geometry; aggregate
CPU utilization hid the single-thread bottleneck.

Dataset jobs now retain one sequential Node/server/browser session. A complete
WorldSpec snapshot keys an LRU cache of deterministic CPU terrain and placement
arrays, limited to 64 chunks / 128 MiB of accounted geometry. Changing the world
clears it. Requested chunk order remains unchanged; cache eviction affects work
only, and never removes required sensor geometry. Oversized chunks are generated
normally without retention. Scenes, assets, GPU resources and LiDAR BVHs are
created and disposed for every request. All measurements, noise/weather,
thermal history, labels, previews, packaging, hashes and publication validation
are still computed per packet. No sensor resolution or quality was reduced.

## Throughput and exact parity

Windows, Intel Core i5-12400 (6 cores / 12 threads), NVIDIA RTX 3090 (24 GiB),
Node 25.6.1, Python 3.13.10, Edge 154.0.4258.37 / hardware D3D11;
`PLAYWRIGHT_CHANNEL=msedge`, `PLAYWRIGHT_GPU=1`.

| Run | Before | After | Ratio |
| --- | ---: | ---: | ---: |
| Matched fresh 24 requests, including cold starts and full publication | 425.62 s | 76.62 s | 5.55x |
| All original 300 pilot requests, including complete validation/publication | 5,076.44 s (historical SF-10 run) | 657.62 s | 7.72x |
| Mean complete 300-packet job cost per packet | 16.92 s | 2.19 s | 7.72x |

The matched subset covers airfield and harbor worlds, all ten condition/time
variants, viewpoint changes and nonresident objects. Its exact request indices,
request hashes, environment, stage means, fresh-capture counts and manifests are
in [the benchmark report](../../.ecc/benchmarks/sf10-collection.json).
The instrumented reference used `03f2259` behavior with timing-only additions.
Each measured run used a separate capture root and new output directory; all
reported generation runs had zero reused captures.

The complete replay used the unchanged frozen request file with SHA-256
`b189a72bd4524344bf8cf905aeea6b33465bcd7abeff80a86a4037f8d28ab010`.
Its 320x192 RGB/IR and 32x256 LiDAR profile is exactly the original SF-10 profile.
All 12,000 data files across 300 captures are byte-identical to the immutable
original pilot: raw observations, reference arrays, previews, thermal states,
masks, calibration, annotations and truth. Only runtime telemetry and manifest
provenance differ. The original manifest remains SHA-256
`c71680f7e2d2451991a772a05c6b977a8944c476cd453d1dcf1b9f0bace47ebe`;
the optimized manifest is
`05b0898a5aca02faa7e1bc492686ec9ae7fbbdb1d59d8ce087a1bdcfe57f5908`.
See [complete comparison](sf10-performance/full-comparison.json).

The replay generated 249 chunks for 6,630 requested chunk uses (96.2% fewer
meshing operations). Retained cache peaked at 37 chunks / 133,383,544 accounted
bytes, below its 128 MiB budget. Browser heap peaked at 367,126,114 bytes and
Node RSS at 168,202,240 bytes. Median browser capture time was 906.05 ms;
the 4,320.8 ms p95 includes requests that generated uncached terrain. GPU memory
is not separately measured. These are observed process/cache measurements,
not a guarantee that the entire browser uses only the retention budget.

The [independent audit](sf10-performance/pilot-audit.json) retained the original
200/50/50 split, 1,500 object records, 510 eligible / 990 ignored records, and
equal geometry identities across all 30 ten-condition sequences. It independently
recomputed masks, tight boxes, fractions, LiDAR counts, eligibility, calibration,
request hashes and group isolation.

## Final contract and regression checks

Browser QA initially caught telemetry fields added to the strict CaptureResult
wire envelope. The final change keeps timings/cache counters only in the metadata
artifact and validates the canonical CaptureResult schema before publication.
A fresh final 24-request replay passed this boundary and retained all 960 data
files byte-for-byte; see [final parity](sf10-performance/final-wire-parity.json).
This additional run took 92.10 s while browser QA and repository verification
ran concurrently; use the earlier matched run for the focused performance
comparison. The telemetry correction does not change the browser sensor code
tested in the complete 300-request replay.

`npm run verify` passed: 65 contract, 22 world, 30 sensor, 8 asset and 118 backend
tests, capture-worker typecheck and production build. New checks cover exact
world-snapshot invalidation, negative chunk coordinates, LRU/byte retention,
oversized chunk support, process reuse/closure, crash, context loss, timeout,
cancellation, wrong identity/missing artifacts and telemetry rejection before
atomic publication.

Production-built Edge browser checks passed for synchronized 640x384 / 64x512
capture panes, cancellation, capture after browser closure, independent noise
seeds and continued thermal history. The browser-closure fixture still expected
the pre-SF-10 artifact inventory; adding the existing `ir_instance` and `rgb_raw`
artifacts fixed its assertion, and its isolated rerun passed. The other three
scenarios passed in the suite. Exact commands, exit codes, source/report/log
hashes are in [verification](sf10-performance/verification.json).

## Reproduction and limits

Use the existing dataset command with GPU enabled; persistent execution is now
the default. `--single-use` keeps fresh-browser reference execution available.
See [collection instructions](../CAPTURE.md#dataset-throughput). For repeat
benchmarks, use new outputs and separate `YULAB_CAPTURE_ROOT` paths so previous
captures cannot be mistaken for newly generated data.

```powershell
$env:PLAYWRIGHT_CHANNEL='msedge'
$env:PLAYWRIGHT_GPU='1'
$env:YULAB_CAPTURE_ROOT=(Join-Path (Get-Location) 'artifacts/perf-sf10/full-captures')
backend\.venv\Scripts\python.exe tools\dataset-job.py --requests artifacts\sf10\requests-v4.json --output artifacts\perf-sf10\full-300
backend\.venv\Scripts\python.exe tools\compare-capture-datasets.py artifacts\sf10\pilot-300-v4 artifacts\perf-sf10\full-300
backend\.venv\Scripts\python.exe tools\audit-sf10-pilot.py artifacts\perf-sf10\full-300 artifacts\sf10\requests-v4.json
```

The dataset replay is stored separately from the original pilot. Its published
manifest records `b0935f0`. The final wire/parity regression was run on the tree
subsequently committed as `99131c8`; source hashes anchor that tested tree.
Initial meshing remains expensive for a new world/region, so gains depend on
reuse between related poses and conditions. This measurement does not establish
640x384 dataset throughput or speed for a different world per packet. Background
host workloads were not controlled; the 300-packet speed ratio uses the historical
baseline. At the measured profile and comparable layout reuse, 3,000 packets
project to about 110 minutes rather than 14.1 hours; this is an estimate.
