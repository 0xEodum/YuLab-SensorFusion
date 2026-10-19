"""Record whole-command runtime and NVIDIA telemetry for capture or learning.

Use --output DIR -- COMMAND ARGS. Refuses to overwrite an existing profile.
GPU readings include other processes; they are not process-local attribution.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("A command is required after --")
    args.output.mkdir(parents=True, exist_ok=False)
    fields = ["utilization.gpu", "utilization.memory", "power.draw", "temperature.gpu", "memory.used", "clocks.sm"]
    names = ["gpu_util_percent", "memory_util_percent", "power_w", "temperature_c", "memory_mib", "sm_clock_mhz"]
    identity = subprocess.check_output(["nvidia-smi", f"--id={args.gpu}", "--query-gpu=name,uuid,driver_version,power.limit", "--format=csv"], text=True).strip()
    processes = subprocess.check_output(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv"], text=True).strip()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    with (args.output / "gpu.csv").open("w", encoding="utf-8") as gpu, (args.output / "command.log").open("w", encoding="utf-8") as log:
        monitor = subprocess.Popen(["nvidia-smi", f"--id={args.gpu}", "--query-gpu=timestamp," + ",".join(fields), "--format=csv,noheader,nounits", "-lms", "100"], stdout=gpu, stderr=log)
        started = time.perf_counter()
        try:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        finally:
            wall_s = time.perf_counter() - started
            monitor.terminate()
            monitor.wait(timeout=10)
    samples = []
    with (args.output / "gpu.csv").open(encoding="utf-8") as stream:
        for row in csv.reader(stream):
            try:
                if len(row) == 7:
                    samples.append([float(v) for v in row[1:]])
            except ValueError:
                continue
    summary = {"command": command, "source_revision": revision, "source_dirty": dirty, "exit_code": result.returncode,
        "wall_s": wall_s, "gpu_identity": identity, "compute_processes_before": processes,
        "attribution": "device-wide, includes unrelated processes", "sample_period_ms": 100,
        "samples": len(samples), "telemetry": {name: {"mean": statistics.mean(s[i] for s in samples),
            "max": max(s[i] for s in samples), "min": min(s[i] for s in samples)} for i, name in enumerate(names)} if samples else {}}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
