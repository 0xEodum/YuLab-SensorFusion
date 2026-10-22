"""Profile the unchanged accepted ensemble, separating end-to-end and forward cost."""
from __future__ import annotations

import argparse
import cProfile
import json
from pathlib import Path
import pstats
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import numpy as np
import torch
import psutil
from learning.decision_inference import DecisionFusionPredictor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--bundle", type=Path, default=ROOT / "docs/evidence/sf-quality/model-bundle.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=60)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    model = DecisionFusionPredictor([ROOT / v["path"] for v in bundle["experts"]], "cuda",
        [v["sha256"] for v in bundle["experts"]])
    assert model.sha256 == bundle["checkpoint_sha256"]
    load_s = time.perf_counter() - started
    request = {"capture_id": args.capture_id}
    for _ in range(10):
        model.infer_capture(args.observations, request)
    benchmark_start = time.time()
    latencies = [model.infer_capture(args.observations, request)["latency_ms"] for _ in range(args.repeat)]
    benchmark_end = time.time()
    # Forward hooks only record CUDA stream spans. They do not synchronize each
    # head; CPU cProfile is a separate instrumented pass, not a speed benchmark.
    events, pending, handles = [], {}, []

    def before(module, _inputs):
        start = torch.cuda.Event(enable_timing=True)
        start.record()
        pending[id(module)] = start

    def after(module, _inputs, _output):
        end = torch.cuda.Event(enable_timing=True)
        end.record()
        events.append((pending.pop(id(module)), end))

    for head in model.models:
        handles.extend([head.register_forward_pre_hook(before), head.register_forward_hook(after)])
    profiler = cProfile.Profile()
    try:
        profiler.enable()
        for _ in range(10):
            prediction = model.infer_capture(args.observations, request)
        profiler.disable()
        torch.cuda.synchronize()
    finally:
        for handle in handles:
            handle.remove()
    profiler.dump_stats(str(args.output / "host.prof"))
    stats = pstats.Stats(profiler)
    rows = [{"file": Path(file).name, "line": line, "function": name, "calls": value[1],
        "self_s": value[2], "cumulative_s": value[3]} for (file, line, name), value in stats.stats.items()]
    top = sorted(rows, key=lambda r: -r["cumulative_s"])[:35]
    spans = [a.elapsed_time(b) for a, b in events]
    summary = {"torch": torch.__version__, "gpu": torch.cuda.get_device_name(),
        "model_load_s": load_s, "checkpoint_sha256": model.sha256, "heads": len(model.models),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "process_peak_rss_bytes": getattr(psutil.Process().memory_info(), "peak_wset", psutil.Process().memory_info().rss),
        "warmup": 10, "repetitions": args.repeat,
        "benchmark_start_unix_s": benchmark_start, "benchmark_end_unix_s": benchmark_end,
        "end_to_end_ms": {"p50": float(np.percentile(latencies, 50)), "p95": float(np.percentile(latencies, 95))},
        "instrumented_forward_stream_span_ms_per_capture": sum(spans) / 10,
        "instrumented_host_wall_s": stats.total_tt, "instrumented_captures": 10,
        "host_cumulative_top": top,
        "limits": ["single-frame eager inference, not training or maximum batch throughput",
                   "CUDA event spans include host launch gaps; they are not active-kernel time",
                   "cProfile timings are instrumented and overlap across callers"]}
    (args.output / "prediction.json").write_text(json.dumps(prediction, indent=2) + "\n", encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
