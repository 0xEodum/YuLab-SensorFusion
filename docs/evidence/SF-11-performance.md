# SF-11 staged training and validation performance

2026-10-02. **Performance follow-up accepted locally.** SF-11 overall remains
IN PROGRESS. Original frozen checkpoints, test reports, data and preprocessing
were preserved; optimization uses train/validation and separate run directories.

## Outcome

The complete 40-epoch budget for all four models, including Python startup,
loading, every-epoch validation and artifact writes, took **80.76 s** versus
**235.59 s** for the already-batched eager implementation: **2.92x faster**.
All 160 epoch histories, selected epochs, selected model/optimizer tensors and
saved validation predictions are **exactly identical** to that eager run.
The older per-frame loss is separately checked for loss/gradient parity within
FP32 tolerance; its full training trajectory is not claimed bitwise identical.

GPU utilization sampled at 100 ms increased from **41.34% to 79.23%** over the
whole command. The accepted run recorded 404/738 samples at 100% utilization,
versus zero in the eager run. Mean power increased from 88.40 to 110.92 W;
peak power from 140.66 to 189.59 W. These are same-machine NVIDIA telemetry,
including initialization, validation, writing and shutdown, not SM occupancy.
Nsight's union of kernel intervals covered **93.79% of the training epoch**.

| Model | Eager runtime | Accepted runtime | Speedup |
| --- | ---: | ---: | ---: |
| RGB | 54.65 s | 14.76 s | 3.70x |
| IR | 56.41 s | 17.15 s | 3.29x |
| LiDAR | 53.12 s | 15.31 s | 3.47x |
| Fusion | 66.00 s | 28.23 s | 2.34x |

The exact runtime fields and parity checks are in
[performance-complete.json](sf11/performance-complete.json). Source hashes are
included. Implementation checkpoints: `34e8011` (batched/native/graph compute),
`35604d5` (fixed AdamW graph prefix), `b2eeffc` (debug allocation fill), and
`978c150` (native validation clipping). The accepted full run uses `978c150`.

## Profiling stages and hypotheses

1. **Loading boundary.** `load_split` already loads the preprocessed cache and
   uploads the complete pilot once. Train plus validation features occupy
   638,112,000 bytes (about 609 MiB). Warm startup was typically about 1.0 s for
   train and 0.3 s for validation. A cold/outlier startup took about 15.6 s;
   it was retained as exploratory evidence. Neither disk loading nor camera
   upload occurs per training update. A direct-to-VRAM disk loader would not
   address the measured steady-state bottleneck.
2. **Original eager trace.** Per-frame SciPy assignment repeatedly transfers
   costs and creates labels/loss graphs; per-frame prediction extraction also
   synchronizes. Four profiled steps had 17,200 launches, 1,267 stream syncs,
   about 589 ms self CPU and 90 ms self CUDA time. Existing batched changes were
   reviewed and validated: one matching transfer per batch, packed targets,
   vectorized loss and prediction transfer, reused condition matches.
3. **Native assignment.** A bounded primal-dual CUDA assignment kernel removes
   the CPU matching round trip. It uses double potentials over the unchanged
   FP32 costs, supports empty/full targets and runs on PyTorch's current stream.
   Invalid counts/nonfinite costs return a device sentinel rather than hang or
   access invalid memory. This kernel alone did not consistently improve full
   wall time; its principal benefit is enabling graph capture.
4. **Graph compute.** Fixed-shape forward, loss, assignment, backward and
   clipping are captured. Actual final batch shapes have separate graphs.
   Gradient buffers are retained and rebound correctly across those shapes.
   Dataset order and supervision enter through stable device indices/buffers.
5. **AdamW prefix.** Its fixed foreach operations are captured. CPU step counts,
   CPU bias corrections and the final update operations keep the original
   arithmetic/order. Warmup/capture restores any temporary optimizer mutations.
   Standard checkpoint state remains intact. A benchmark defect was corrected:
   mapping the entire checkpoint to CUDA incorrectly moved non-capturable
   AdamW counters there and introduced scalar readbacks. Optimizer restore now
   keeps CPU counters and uses fresh state copies before the measured epoch.
6. **Allocation debug filling.** Nsight showed roughly 24,000 fill kernels in
   an epoch. Accelerated execution disables debug filling of empty allocations;
   deterministic algorithms remain enabled. Every consumed buffer is completely
   initialized. Full histories/tensors remained exact. `--deterministic-fill`
   restores the debugging behavior.
7. **Validation geometry.** CPU polygon clipping became the largest remaining
   validation component. A second CUDA kernel batches exact FP32 upright IoU.
   CPU-prepared corners/endpoints/volumes preserve NumPy rounding; native FMA is
   disabled. It passes exact scalar IoU checks on random rotated boxes and
   empty/full frame shapes. Score-ranked matching and metric reductions remain
   independent CPU code. The measured geometry phase fell from about 0.10 s to
   0.04 s; the validation report remains exact.

## Frozen-checkpoint timings

Same dataset hash, seed 11, checkpoint hash, FP32, batch 32, 2,100 training and
450 validation captures; fresh model/optimizer restore before each complete
epoch. Phase measurements synchronize deliberately. Complete epoch timing
preserves asynchronous execution. Warmup/profiler overhead is excluded from
these measurements and startup/setup are reported separately.

| Variant | Training epoch | Training + validation |
| --- | ---: | ---: |
| Original per-frame reference | 7.148 s | 7.801 s |
| Batched eager + cached evaluation | 1.553 s | 1.716 s |
| Native assignment, eager execution | 1.601 s | 1.806 s |
| Graph compute, eager optimizer | 0.344 s | 0.453 s |
| Graph compute + AdamW prefix | 0.313 s | 0.428 s |
| Above, allocation debug fill disabled | 0.269 s | 0.406 s |
| Above, native validation geometry | 0.288 s | 0.348 s |

This is about **22.4x** for the frozen complete epoch relative to the original
implementation. It is distinct from the **2.92x** measured complete training
command relative to the already-batched eager path. GPU clocks fluctuate under
WDDM; small differences between neighboring variants are not universal gains.
The complete runs include initial low-confidence validation and checkpoint I/O.
[performance-phases.json](sf11/performance-phases.json) retains each command's
configuration, provenance, startup, loss/gradient checks and phase measurements.

## NVIDIA tooling and traces

Verified locally: Nsight Systems **2025.5.2.266**, Nsight Compute **2025.4.1.0**,
CUDA toolkit **13.1**, driver **591.86**, PyTorch **2.13.0+cu130**, RTX 3090/24 GiB
under Windows WDDM. Nsight Systems is installed but not on PATH. Nsight Compute
successfully collected `SpeedOfLight` counters for the matcher (seven replay
passes); its measured kernel duration was 36.16 us under instrumentation. Its
small grid is intentional for the bounded pilot matcher, not a GPU-saturation
benchmark.

The earlier batched trace (`nsight-selected-stage1`) had 61,082 ordinary launches
and 10,048 stream synchronizations; that exploratory trace also included the
optimizer-counter restore defect described above. The accepted trace has 147
graph launches, 202 ordinary launches and eight stream synchronizations across
training/validation. Graph replay still executes individual device kernels:
it removes per-kernel CPU dispatch, rather than asserting kernel fusion.

`nsight-accepted.sqlite` records a 0.2920 s training NVTX range with 0.2739 s of
kernel activity (93.79%), and a 0.0633 s validation range with 0.0167 s of kernel
activity. Remaining validation time includes CPU corner construction, ranked
matching, NumPy formatting and metric reduction. The accepted full run spent
12.41 s in validation and 4.08 s writing artifacts across all four models.
The tiny 173k-parameter fusion network cannot consume the RTX 3090's peak SM,
memory bandwidth and power simultaneously. Whole-job activity and kernel
occupancy are different quantities; low peak power alone does not establish an
idle pipeline.

Local trace artifacts remain under `artifacts/sf11/`:

- `nsight-selected-stage1.nsys-rep`, `.sqlite`, `-stats.csv` (exploratory).
- `nsight-accepted.nsys-rep`, `.sqlite`, `-stats.csv` (accepted path).
- `ncu-matcher.ncu-rep`, `ncu-matcher-details.csv`.
- `performance/full-eager/` and `performance/full-native-evaluation/` retain
  logs, 100 ms GPU telemetry, complete histories, checkpoints and predictions.

Profiler methodology follows the
[NVIDIA CLI capture-range guide](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)
and [PyTorch CUDA graph guidance](https://pytorch.org/blog/accelerating-pytorch-with-cuda-graphs/).

## Reproduce and roll back

Use the measured Python environment or the optional pinned learning environment
described in [LEARNING_BASELINES.md](../LEARNING_BASELINES.md). The native build
requires MSVC and CUDA. This machine's compiler required the explicit
`-AllowUnsupportedCudaCompiler` flag; that is retained in the build manifest,
not silently enabled by the script. Builds target `sm_86` and require a separate
portability validation on other hardware/OS/toolchains.

```powershell
./tools/build-learning-cuda.ps1 -AllowUnsupportedCudaCompiler
python tools/profile-learning-run.py --execution eager --epochs 40 --output artifacts/sf11/performance/repro-eager
python tools/profile-learning-run.py --execution cuda-graph --epochs 40 --output artifacts/sf11/performance/repro-fast
python tools/summarize-learning-performance.py --eager artifacts/sf11/performance/repro-eager --accelerated artifacts/sf11/performance/repro-fast --output artifacts/sf11/performance/repro-parity.json
python tools/benchmark-learning.py --variant graph-optimizer --skip-deterministic-fill --native-evaluation --steps 40 --output artifacts/sf11/performance/repro-phases.json
$nsys='C:/Program Files/NVIDIA Corporation/Nsight Systems 2025.5.2/target-windows-x64/nsys.exe'
& $nsys profile --trace=cuda,nvtx --sample=none --cpuctxsw=none --cuda-graph-trace=node --capture-range=cudaProfilerApi --capture-range-end=stop --output=artifacts/sf11/repro-nsight python tools/benchmark-learning.py --variant graph-optimizer --skip-deterministic-fill --native-evaluation --nsight --steps 5 --output artifacts/sf11/repro-nsight.json
```

Normal training automatically uses the validated native build when available:

```powershell
python tools/learning-pilot.py train --run-root artifacts/sf11/optimized-runs
```

`--execution eager` is the rollback. Explicit CUDA mode fails on a missing/stale
build; auto falls back to eager. The library manifest hashes both source and DLL.
Graph mode checks nonfinite losses at epoch end, with a flag tracking every
step; failure is deferred until that boundary instead of synchronizing each
update. Arbitrary tied assignment costs can choose another equally optimal
permutation than SciPy; the measured pilot has exact complete-budget parity.

Verification: 26 focused learning/capture tests passed in the installed CUDA
environment; backend service suite passed 127 tests with one optional-learning
skip in its separate service environment. `compileall` and `git diff --check`
passed. No frontend/contracts/world code changed. New profiling artifacts do
not overwrite the original baseline/test artifacts, and the sealed test was
not accessed for performance selection.
