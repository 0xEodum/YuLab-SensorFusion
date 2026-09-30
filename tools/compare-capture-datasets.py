"""Require byte-identical sensor/label/truth files, excluding runtime telemetry."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.dataset import digest, validate_manifest  # noqa: E402


def compare(before: Path, after: Path) -> dict:
    left, right = validate_manifest(before), validate_manifest(after)
    old = {x["capture_id"]: x for x in left["captures"]}
    compared = 0
    phases = []
    before_phases = []
    for entry in right["captures"]:
        id_ = entry["capture_id"]
        if id_ not in old or any(entry[k] != old[id_][k] for k in ("split", "group_id")):
            raise ValueError(f"Missing or changed capture/split: {id_}")
        a, b = before / id_, after / id_
        names = {p.name for p in a.iterdir() if p.is_file()}
        if names != {p.name for p in b.iterdir() if p.is_file()}:
            raise ValueError(f"Changed file inventory: {id_}")
        for name in sorted(names - {"metadata_json"}):
            if digest(a / name) != digest(b / name):
                raise ValueError(f"Output parity failed: {id_}/{name}")
            compared += 1
        am, bm = [json.loads((p / "metadata_json").read_text()) for p in (a, b)]
        # Only timing/memory/cache counters and corresponding file provenance can differ.
        runtime = {"elapsed_ms", "render_elapsed_ms", "timings_ms", "total_browser_ms",
                   "node_rss_bytes", "browser_heap_bytes", "gpu_memory_bytes", "geometry_cache"}
        if {k: v for k, v in am.items() if k not in runtime} != \
           {k: v for k, v in bm.items() if k not in runtime}:
            raise ValueError(f"Non-runtime metadata changed: {id_}")
        phases.append(bm)
        before_phases.append(am)
    result = {"captures": len(right["captures"]), "identical_files": compared,
              "parity": "byte-identical; runtime telemetry excluded",
              "before_manifest_sha256": digest(before / "manifest.json"),
              "after_manifest_sha256": digest(after / "manifest.json"),
              "after_mean_phase_ms": {k: statistics.mean(p["timings_ms"][k] for p in phases)
                  for k in phases[0].get("timings_ms", {})},
              "before_mean_phase_ms": {k: statistics.mean(p["timings_ms"][k] for p in before_phases)
                  for k in before_phases[0].get("timings_ms", {})},
              "after_capture_browser_ms": {
                  "median": statistics.median(p["total_browser_ms"] for p in phases),
                  "p95": float(sorted(p["total_browser_ms"] for p in phases)[int(0.95 * (len(phases) - 1))]),
              },
              "peak_cache_bytes": max(p.get("geometry_cache", {}).get("bytes", 0) for p in phases),
              "peak_cache_chunks": max(p.get("geometry_cache", {}).get("chunks", 0) for p in phases),
              "peak_browser_heap_bytes": max(p["browser_heap_bytes"] or 0 for p in phases),
              "peak_node_rss_bytes": max(p["node_rss_bytes"] for p in phases)}
    for label, path in (("before", before), ("after", after)):
        metrics = path / "metrics.json"
        if metrics.exists():
            result[label] = json.loads(metrics.read_text())
    if len(left["captures"]) == len(right["captures"]) and "before" in result and "after" in result:
        if result["before"]["reused_captures"] or result["after"]["reused_captures"]:
            raise ValueError("Throughput comparison requires fresh captures")
        result["speedup"] = result["before"]["elapsed_s"] / result["after"]["elapsed_s"]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(args.before, args.after)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
